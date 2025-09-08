"""
GPT Planning API Endpoints

Provides intelligent order batch planning using GPT-4 analysis
combined with cutting optimization algorithms.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import logging

from .base import get_db
from .. import models
from ..services.gpt_planner import GPTPlanner, SmartPlanResult
from ..services.cutting_optimizer import CuttingOptimizer

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# REQUEST/RESPONSE SCHEMAS
# ============================================================================

class PlanningCriteria(BaseModel):
    """Planning criteria for GPT analysis"""
    prioritize_pending: bool = Field(True, description="Prioritize orders that resolve pending items")
    max_pending_days: int = Field(7, description="Maximum days to consider for pending orders")
    prefer_complete_orders: bool = Field(True, description="Prefer batches that complete entire orders")
    client_priority_list: Optional[List[str]] = Field(None, description="Prioritized client names")

class SmartPlanRequest(BaseModel):
    """Request for smart plan generation"""
    candidate_order_ids: List[str] = Field(..., description="Order IDs selected by user as candidates")
    include_pending: bool = Field(True, description="Include pending orders in analysis")
    max_batch_size: Optional[int] = Field(None, description="Override default max batch size")
    planning_criteria: Optional[PlanningCriteria] = Field(None, description="Additional planning parameters")

class GPTAnalysisResponse(BaseModel):
    """GPT analysis results"""
    recommended_orders: List[str] = Field(..., description="Orders GPT recommends for processing")
    deferred_orders: List[str] = Field(..., description="Orders GPT suggests to defer")
    reasoning: str = Field(..., description="GPT's explanation of selection logic")
    confidence: float = Field(..., description="GPT's confidence score (0-1)")
    expected_pending: int = Field(..., description="Expected pending orders after processing")

class PerformanceMetrics(BaseModel):
    """Performance timing metrics"""
    gpt_response_time: float = Field(..., description="Time for GPT analysis (seconds)")
    optimization_time: float = Field(..., description="Time for cutting optimization (seconds)")
    total_time: float = Field(..., description="Total processing time (seconds)")

class SmartPlanResponse(BaseModel):
    """Complete smart plan response"""
    status: str = Field(..., description="Response status (success/error)")
    gpt_analysis: Optional[GPTAnalysisResponse] = Field(None, description="GPT analysis results")
    optimization_result: Optional[Dict[str, Any]] = Field(None, description="Cutting optimization results")
    performance_metrics: PerformanceMetrics = Field(..., description="Performance timing data")
    error_message: Optional[str] = Field(None, description="Error message if failed")

class GPTStatusResponse(BaseModel):
    """GPT service status response"""
    available: bool = Field(..., description="Whether GPT planning is available")
    configured: bool = Field(..., description="Whether OpenAI API key is configured")
    model: Optional[str] = Field(None, description="GPT model being used")
    enabled: bool = Field(..., description="Whether GPT planning is enabled")

# ============================================================================
# GPT PLANNING ENDPOINTS
# ============================================================================

@router.get("/planning/gpt-status", response_model=GPTStatusResponse, tags=["GPT Planning"])
def get_gpt_status(db: Session = Depends(get_db)):
    """
    Check GPT planning service status and configuration.
    Used by frontend to determine if Smart Plan button should be shown.
    """
    try:
        planner = GPTPlanner(db)
        
        return GPTStatusResponse(
            available=planner.is_available(),
            configured=bool(planner.api_key),
            model=planner.model if planner.is_available() else None,
            enabled=planner.enabled
        )
    except Exception as e:
        logger.error(f"Error checking GPT status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to check GPT status: {str(e)}")

@router.post("/planning/smart-plan", response_model=SmartPlanResponse, tags=["GPT Planning"])
def create_smart_plan(request: SmartPlanRequest, db: Session = Depends(get_db)):
    """
    Generate an intelligent cutting plan using GPT analysis.
    
    This endpoint:
    1. Analyzes candidate orders and pending orders using GPT-4
    2. Gets GPT's recommendation for optimal batch selection
    3. Runs cutting optimization on GPT's selected orders
    4. Returns both GPT insights and optimization results
    
    This complements the traditional "Generate Plan" endpoint by providing
    AI-assisted order selection before optimization.
    """
    try:
        # Validate request
        if not request.candidate_order_ids:
            raise HTTPException(
                status_code=400, 
                detail="At least one candidate order ID is required"
            )
        
        # Initialize GPT planner
        planner = GPTPlanner(db)
        
        # Check if GPT planning is available
        if not planner.is_available():
            raise HTTPException(
                status_code=503,
                detail="GPT planning service is not available. Please check configuration."
            )
        
        # Override batch size if provided
        if request.max_batch_size:
            planner.max_batch_size = request.max_batch_size
        
        # Convert planning criteria to dict
        criteria_dict = {}
        if request.planning_criteria:
            criteria_dict = request.planning_criteria.dict()
        
        # Execute smart planning
        logger.info(f"Starting smart plan for {len(request.candidate_order_ids)} candidates")
        result: SmartPlanResult = planner.smart_plan_batch(
            candidate_order_ids=request.candidate_order_ids,
            include_pending=request.include_pending,
            planning_criteria=criteria_dict
        )
        
        # Log the complete result structure
        logger.info(f"GPT Smart Plan Result - Success: {result.success}")
        if result.success and result.gpt_recommendation:
            logger.info(f"GPT Recommendation - Recommended: {result.gpt_recommendation.recommended_orders}")
            logger.info(f"GPT Recommendation - Deferred: {result.gpt_recommendation.deferred_orders}")
            logger.info(f"GPT Recommendation - Confidence: {result.gpt_recommendation.confidence}")
            logger.info(f"GPT Recommendation - Reasoning: {result.gpt_recommendation.reasoning}")
        
        # Log optimization result structure
        if result.optimization_result:
            logger.info(f"Optimization Result Keys: {list(result.optimization_result.keys())}")
            if 'cut_rolls_generated' in result.optimization_result:
                cut_rolls = result.optimization_result['cut_rolls_generated']
                logger.info(f"Cut Rolls Generated Type: {type(cut_rolls)}, Length: {len(cut_rolls) if cut_rolls else 'None'}")
                if cut_rolls:
                    logger.info(f"First Cut Roll Sample: {cut_rolls[0] if len(cut_rolls) > 0 else 'Empty'}")
        else:
            logger.warning("Optimization result is None/empty")
        
        logger.info(f"Performance Metrics: {result.performance_metrics}")
        if result.error_message:
            logger.error(f"Smart Plan Error Message: {result.error_message}")
        
        # Build response
        if result.success:
            response = SmartPlanResponse(
                status="success",
                gpt_analysis=GPTAnalysisResponse(
                    recommended_orders=result.gpt_recommendation.recommended_orders,
                    deferred_orders=result.gpt_recommendation.deferred_orders,
                    reasoning=result.gpt_recommendation.reasoning,
                    confidence=result.gpt_recommendation.confidence,
                    expected_pending=result.gpt_recommendation.expected_pending
                ),
                optimization_result=result.optimization_result,
                performance_metrics=PerformanceMetrics(
                    gpt_response_time=result.performance_metrics.get("gpt_response_time", 0),
                    optimization_time=result.performance_metrics.get("optimization_time", 0),
                    total_time=result.performance_metrics.get("total_time", 0)
                )
            )
            
            logger.info(f"Smart plan completed successfully in {result.performance_metrics.get('total_time', 0):.2f}s")
            return response
        else:
            # Return error response
            return SmartPlanResponse(
                status="error",
                performance_metrics=PerformanceMetrics(
                    gpt_response_time=result.performance_metrics.get("gpt_response_time", 0),
                    optimization_time=result.performance_metrics.get("optimization_time", 0),
                    total_time=result.performance_metrics.get("total_time", 0)
                ),
                error_message=result.error_message
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Smart planning failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Smart planning failed: {str(e)}")

@router.post("/planning/quick-gpt-analysis", tags=["GPT Planning"])
def quick_gpt_analysis(request: SmartPlanRequest, db: Session = Depends(get_db)):
    """
    Get GPT analysis only (without running optimization).
    
    Useful for previewing GPT's recommendations before committing to
    the full optimization process. Frontend can use this to show
    users what GPT would recommend.
    """
    try:
        if not request.candidate_order_ids:
            raise HTTPException(
                status_code=400,
                detail="At least one candidate order ID is required"
            )
        
        planner = GPTPlanner(db)
        
        if not planner.is_available():
            raise HTTPException(
                status_code=503,
                detail="GPT planning service is not available"
            )
        
        # Collect order data
        order_data = planner._collect_order_data(
            request.candidate_order_ids, 
            request.include_pending
        )
        
        # Get GPT recommendation only
        criteria_dict = request.planning_criteria.dict() if request.planning_criteria else {}
        gpt_recommendation = planner._get_gpt_recommendation(order_data, criteria_dict)
        
        return {
            "status": "success",
            "gpt_analysis": {
                "recommended_orders": gpt_recommendation.recommended_orders,
                "deferred_orders": gpt_recommendation.deferred_orders,
                "reasoning": gpt_recommendation.reasoning,
                "confidence": gpt_recommendation.confidence,
                "expected_pending": gpt_recommendation.expected_pending
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Quick GPT analysis failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"GPT analysis failed: {str(e)}")

# ============================================================================
# FALLBACK ENDPOINT
# ============================================================================

@router.post("/planning/smart-plan-with-fallback", response_model=SmartPlanResponse, tags=["GPT Planning"])
def smart_plan_with_fallback(request: SmartPlanRequest, db: Session = Depends(get_db)):
    """
    Smart plan with automatic fallback to traditional optimization.
    
    If GPT fails or is unavailable, automatically falls back to running
    traditional cutting optimization on all candidate orders.
    """
    try:
        # Try GPT planning first
        planner = GPTPlanner(db)
        
        if planner.is_available():
            try:
                # Attempt smart planning
                result = planner.smart_plan_batch(
                    candidate_order_ids=request.candidate_order_ids,
                    include_pending=request.include_pending,
                    planning_criteria=request.planning_criteria.dict() if request.planning_criteria else {}
                )
                
                if result.success:
                    logger.info("Smart planning succeeded")
                    return SmartPlanResponse(
                        status="success",
                        gpt_analysis=GPTAnalysisResponse(
                            recommended_orders=result.gpt_recommendation.recommended_orders,
                            deferred_orders=result.gpt_recommendation.deferred_orders,
                            reasoning=result.gpt_recommendation.reasoning,
                            confidence=result.gpt_recommendation.confidence,
                            expected_pending=result.gpt_recommendation.expected_pending
                        ),
                        optimization_result=result.optimization_result,
                        performance_metrics=PerformanceMetrics(**result.performance_metrics)
                    )
            except Exception as e:
                logger.warning(f"GPT planning failed, falling back to traditional: {str(e)}")
        
        # Fallback to traditional optimization
        logger.info("Using traditional optimization fallback")
        optimizer = CuttingOptimizer()  # Use default width (118)
        
        from datetime import datetime
        start_time = datetime.now()
        
        # Convert order IDs to requirements format
        order_requirements = []
        for order_id in request.candidate_order_ids:
            order = db.query(models.OrderMaster).filter(
                models.OrderMaster.frontend_id == order_id
            ).first()
            
            if order:
                order_items = db.query(models.OrderItem).filter(
                    models.OrderItem.order_id == order.id
                ).all()
                
                for item in order_items:
                    order_requirements.append({
                        'width': float(item.width),
                        'quantity': item.quantity,
                        'gsm': item.gsm,
                        'bf': item.bf if hasattr(item, 'bf') else 0,
                        'order_id': order.frontend_id,
                        'client_name': order.client.company_name if order.client else "Unknown"
                    })
        
        # Use the new optimization algorithm
        optimization_result = optimizer.optimize_with_new_algorithm(
            order_requirements=order_requirements,
            pending_orders=[],  # Will be handled separately
            available_inventory=[],  # Will be handled separately 
            interactive=False
        )
        total_time = (datetime.now() - start_time).total_seconds()
        
        return SmartPlanResponse(
            status="success",
            optimization_result=optimization_result,
            performance_metrics=PerformanceMetrics(
                gpt_response_time=0,
                optimization_time=total_time,
                total_time=total_time
            ),
            error_message="Used traditional optimization (GPT unavailable)"
        )
        
    except Exception as e:
        logger.error(f"Both smart and traditional planning failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Planning failed: {str(e)}")