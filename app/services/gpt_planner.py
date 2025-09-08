"""
GPT-powered intelligent order batch planning service.

This service integrates with OpenAI's GPT-4 to analyze order data and suggest
optimal batch combinations for cutting optimization. The service works alongside
the existing cutting optimizer to provide AI-assisted planning.
"""

import os
import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from .. import models, crud_operations
from .cutting_optimizer import CuttingOptimizer

logger = logging.getLogger(__name__)

# OpenAI integration
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("OpenAI package not available. Install with: pip install openai")

@dataclass
class GPTRecommendation:
    """Represents GPT's batch recommendation with reasoning"""
    recommended_orders: List[str]  # Order IDs selected by GPT
    deferred_orders: List[str]     # Order IDs GPT suggests to defer
    reasoning: str                 # GPT's explanation of decision
    confidence: float              # GPT's confidence score (0-1)
    expected_pending: int          # GPT's prediction of remaining pending orders
    analysis_time: float           # Time taken for GPT analysis

@dataclass
class SmartPlanResult:
    """Complete result from GPT + optimization workflow"""
    gpt_recommendation: GPTRecommendation
    optimization_result: Dict[str, Any]  # From cutting optimizer
    performance_metrics: Dict[str, float]
    success: bool
    error_message: Optional[str] = None

class GPTPlanner:
    """
    GPT-powered intelligent order batch planner.
    
    This service analyzes pending orders and candidate orders to suggest
    optimal batches that minimize pending orders while considering business
    constraints like urgency, batch size limits, and order completeness.
    """
    
    def __init__(self, db: Session, cutting_optimizer: Optional[CuttingOptimizer] = None):
        self.db = db
        self.cutting_optimizer = cutting_optimizer or CuttingOptimizer()  # Use default width (118)
        
        # GPT Configuration from environment
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("GPT_MODEL", "gpt-4")
        self.max_tokens = int(os.getenv("GPT_MAX_TOKENS", "1500"))
        self.temperature = float(os.getenv("GPT_TEMPERATURE", "0.3"))
        self.enabled = os.getenv("GPT_PLANNING_ENABLED", "false").lower() == "true"
        
        # Planning parameters
        self.max_batch_size = int(os.getenv("MAX_BATCH_SIZE", "10"))
        self.pending_priority_days = int(os.getenv("PENDING_ORDER_PRIORITY_DAYS", "5"))
        
        if self.enabled and not self.api_key:
            logger.error("GPT planning enabled but OPENAI_API_KEY not configured")
            self.enabled = False
        
        if self.enabled and not OPENAI_AVAILABLE:
            logger.error("GPT planning enabled but openai package not installed")
            self.enabled = False
            
        if self.enabled:
            self.client = openai.OpenAI(api_key=self.api_key)
            logger.info(f"GPT Planner initialized with model: {self.model}")
    
    def is_available(self) -> bool:
        """Check if GPT planning is available and properly configured"""
        return self.enabled and OPENAI_AVAILABLE and bool(self.api_key)
    
    def smart_plan_batch(self, 
                        candidate_order_ids: List[str],
                        include_pending: bool = True,
                        planning_criteria: Optional[Dict] = None) -> SmartPlanResult:
        """
        Generate a smart plan using GPT analysis + cutting optimization.
        
        Args:
            candidate_order_ids: Order IDs selected by user as candidates
            include_pending: Whether to include pending orders in analysis
            planning_criteria: Additional planning parameters
            
        Returns:
            SmartPlanResult with GPT recommendation and optimization results
        """
        start_time = datetime.now()
        
        try:
            if not self.is_available():
                return SmartPlanResult(
                    gpt_recommendation=None,
                    optimization_result={},
                    performance_metrics={"total_time": 0},
                    success=False,
                    error_message="GPT planning not available or configured"
                )
            
            # Step 1: Collect order data
            logger.info(f"Starting smart planning for {len(candidate_order_ids)} candidate orders")
            order_data = self._collect_order_data(candidate_order_ids, include_pending)
            
            # Step 2: Get GPT recommendation
            gpt_start = datetime.now()
            gpt_recommendation = self._get_gpt_recommendation(order_data, planning_criteria or {})
            gpt_time = (datetime.now() - gpt_start).total_seconds()
            
            if not gpt_recommendation.recommended_orders:
                return SmartPlanResult(
                    gpt_recommendation=gpt_recommendation,
                    optimization_result={},
                    performance_metrics={"gpt_time": gpt_time, "total_time": gpt_time},
                    success=False,
                    error_message="GPT recommended no orders for processing"
                )
            
            # Step 3: Convert GPT's selected orders to requirements format and run optimization
            opt_start = datetime.now()
            order_requirements = self._convert_orders_to_requirements(gpt_recommendation.recommended_orders)
            
            # Log the order requirements being sent to optimizer
            logger.info(f"Converting {len(gpt_recommendation.recommended_orders)} orders to requirements format")
            logger.info(f"Order requirements count: {len(order_requirements)}")
            if order_requirements:
                logger.info(f"Sample order requirement: {order_requirements[0]}")
            
            # Use the new algorithm for optimization
            logger.info("Starting cutting optimization with new algorithm")
            optimization_result = self.cutting_optimizer.optimize_with_new_algorithm(
                order_requirements=order_requirements,
                pending_orders=[],  # Will be handled separately
                available_inventory=[],  # Will be handled separately
                interactive=False
            )
            
            # Log optimization result structure
            logger.info(f"Optimization completed. Result type: {type(optimization_result)}")
            if optimization_result:
                logger.info(f"Optimization result keys: {list(optimization_result.keys()) if isinstance(optimization_result, dict) else 'Not a dict'}")
                if isinstance(optimization_result, dict) and 'cut_rolls_generated' in optimization_result:
                    cut_rolls = optimization_result['cut_rolls_generated']
                    logger.info(f"Cut rolls type: {type(cut_rolls)}, count: {len(cut_rolls) if cut_rolls is not None else 'None'}")
            else:
                logger.warning("Optimization result is None")
            opt_time = (datetime.now() - opt_start).total_seconds()
            
            total_time = (datetime.now() - start_time).total_seconds()
            
            return SmartPlanResult(
                gpt_recommendation=gpt_recommendation,
                optimization_result=optimization_result,
                performance_metrics={
                    "gpt_response_time": gpt_time,
                    "optimization_time": opt_time,
                    "total_time": total_time
                },
                success=True
            )
            
        except Exception as e:
            logger.error(f"Smart planning failed: {str(e)}", exc_info=True)
            total_time = (datetime.now() - start_time).total_seconds()
            
            return SmartPlanResult(
                gpt_recommendation=None,
                optimization_result={},
                performance_metrics={"total_time": total_time},
                success=False,
                error_message=f"Smart planning error: {str(e)}"
            )
    
    def _collect_order_data(self, candidate_order_ids: List[str], include_pending: bool) -> Dict[str, Any]:
        """Collect comprehensive order data for GPT analysis"""
        
        logger.info(f"🔍 COLLECTING ORDER DATA: Input candidate_order_ids = {candidate_order_ids}")
        logger.info(f"🔍 COLLECTING ORDER DATA: include_pending = {include_pending}")
        
        # Get candidate orders with their items
        candidate_orders = []
        for order_id in candidate_order_ids:
            logger.debug(f"🔍 Looking for order with UUID = {order_id}")
            
            # Only use UUID lookup
            order = None
            try:
                import uuid
                uuid_obj = uuid.UUID(order_id)
                order = self.db.query(models.OrderMaster).filter(
                    models.OrderMaster.id == uuid_obj
                ).first()
                if order:
                    logger.debug(f"✅ Found order by UUID: {order.frontend_id or order.id}")
                else:
                    logger.warning(f"❌ Order not found with UUID: {order_id}")
            except (ValueError, TypeError):
                logger.warning(f"❌ Invalid UUID format: {order_id}")
            
            if order:
                order_items = self.db.query(models.OrderItem).filter(
                    models.OrderItem.order_id == order.id
                ).all()
                
                candidate_orders.append({
                    "order_id": str(order.id),  # Always use UUID as string for GPT
                    "client_name": order.client.company_name if order.client else "Unknown",
                    "order_date": order.created_at.isoformat() if order.created_at else None,
                    "total_quantity": sum(item.quantity_rolls for item in order_items),
                    "total_value": sum(item.quantity_kg * item.rate for item in order_items),
                    "widths": [{"width": float(item.width_inches), "quantity": item.quantity_rolls} for item in order_items],
                    "status": order.status.value if hasattr(order.status, 'value') else (order.status or "unknown"),
                    "payment_type": order.payment_type.value if hasattr(order.payment_type, 'value') else (order.payment_type or "unknown")
                })
        
        # Get pending orders if requested
        pending_orders = []
        if include_pending:
            pending_cutoff = datetime.now() - timedelta(days=self.pending_priority_days)
            
            pending_query = self.db.query(models.PendingOrderMaster).filter(
                models.PendingOrderMaster.status == models.PendingOrderStatus.PENDING
            ).all()
            
            for pending in pending_query:
                pending_items = self.db.query(models.PendingOrderItem).filter(
                    models.PendingOrderItem.pending_order_id == pending.id
                ).all()
                
                days_pending = (datetime.now() - pending.created_at).days if pending.created_at else 0
                
                pending_orders.append({
                    "pending_id": pending.frontend_id,
                    "original_order_id": pending.original_order_frontend_id,
                    "client_name": pending.client_name,
                    "days_pending": days_pending,
                    "is_urgent": days_pending >= self.pending_priority_days,
                    "widths": [{"width": item.width, "quantity": item.pending_quantity} for item in pending_items],
                    "total_quantity": sum(item.pending_quantity for item in pending_items)
                })
        
        result = {
            "candidate_orders": candidate_orders,
            "pending_orders": pending_orders,
            "constraints": {
                "max_batch_size": self.max_batch_size,
                "pending_priority_days": self.pending_priority_days,
                "current_date": datetime.now().isoformat()
            }
        }
        
        logger.info(f"🔍 ORDER DATA COLLECTION RESULT:")
        logger.info(f"   📦 Candidate orders found: {len(candidate_orders)}")
        logger.info(f"   ⏳ Pending orders found: {len(pending_orders)}")
        if candidate_orders:
            logger.info(f"   📋 Candidate order IDs: {[order['order_id'] for order in candidate_orders]}")
        else:
            logger.warning(f"   🚨 NO CANDIDATE ORDERS FOUND!")
            
        return result
    
    def _get_gpt_recommendation(self, order_data: Dict[str, Any], criteria: Dict[str, Any]) -> GPTRecommendation:
        """Get batch recommendation from GPT"""
        
        # Build the prompt
        prompt = self._build_analysis_prompt(order_data, criteria)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )
            
            # Parse GPT response
            response_text = response.choices[0].message.content
            logger.info(f"🤖 RAW GPT RESPONSE: {response_text}")
            recommendation = self._parse_gpt_response(response_text, order_data)
            
            return recommendation
            
        except Exception as e:
            logger.error(f"GPT API call failed: {str(e)}")
            raise Exception(f"GPT analysis failed: {str(e)}")
    
    def _get_system_prompt(self) -> str:
        """System prompt that defines GPT's role and constraints"""
        return """You are an expert production planning AI for a paper roll cutting operation. 

Your goal is to analyze order data and suggest optimal batches that:
1. we have to make planning which send nothing into pending order  (highest priority)
2. Consider order urgency and client relationships  
3. Respect batch size limits
4. Prefer batches that can be completed entirely
5. Balance cutting efficiency with business priorities

You will receive candidate orders (pre-selected by user) and pending orders data.
Your job is to recommend which subset of candidate orders to process together.

CRITICAL: You must respond with a valid JSON object containing:
{
  "recommended_orders": ["ORDER-001", "ORDER-002"],
  "deferred_orders": ["ORDER-003"], 
  "reasoning": "Clear explanation of your selection logic",
  "confidence": 0.85,
  "expected_pending": 2
}

Be analytical, consider trade-offs, and explain your reasoning clearly."""
    
    def _build_analysis_prompt(self, order_data: Dict[str, Any], criteria: Dict[str, Any]) -> str:
        """Build detailed prompt with order data and planning criteria"""
        
        prompt_parts = [
            "CUTTING BATCH OPTIMIZATION REQUEST\n",
            "=====================================\n\n"
        ]
        
        # Add candidate orders
        if order_data.get("candidate_orders"):
            prompt_parts.append("CANDIDATE ORDERS (user pre-selected):\n")
            for order in order_data["candidate_orders"]:
                widths_summary = ", ".join([f"{w['width']}mm x{w['quantity']}" for w in order["widths"]])
                prompt_parts.append(
                    f"- {order['order_id']}: {order['client_name']}, "
                    f"Total: {order['total_quantity']} rolls, "
                    f"Widths: [{widths_summary}], "
                    f"Value: ₹{order['total_value']:.0f}\n"
                )
            prompt_parts.append("\n")
        
        # Add pending orders
        if order_data.get("pending_orders"):
            prompt_parts.append("PENDING ORDERS (need urgent attention):\n")
            for pending in order_data["pending_orders"]:
                widths_summary = ", ".join([f"{w['width']}mm x{w['quantity']}" for w in pending["widths"]])
                urgency = " ⚠️ URGENT" if pending["is_urgent"] else ""
                prompt_parts.append(
                    f"- {pending['pending_id']}: {pending['client_name']}, "
                    f"{pending['days_pending']} days pending, "
                    f"Qty: {pending['total_quantity']}, "
                    f"Widths: [{widths_summary}]{urgency}\n"
                )
            prompt_parts.append("\n")
        
        # Add constraints and criteria
        constraints = order_data.get("constraints", {})
        prompt_parts.extend([
            "CONSTRAINTS:\n",
            f"- Maximum batch size: {constraints.get('max_batch_size', 10)} orders\n",
            f"- Orders pending ≥{constraints.get('pending_priority_days', 5)} days are urgent\n",
            f"- Current date: {constraints.get('current_date', 'today')}\n\n"
        ])
        
        # Add planning criteria if provided
        if criteria:
            prompt_parts.append("PLANNING CRITERIA:\n")
            for key, value in criteria.items():
                prompt_parts.append(f"- {key}: {value}\n")
            prompt_parts.append("\n")
        
        # Add instructions
        prompt_parts.extend([
            "INSTRUCTIONS:\n",
            "1. Select optimal subset of candidate orders to process together\n",
            "2. Prioritize combinations that resolve urgent pending orders\n", 
            "3. Consider order urgency, client relationships, and batch efficiency\n",
            "4. Explain your selection logic clearly\n",
            "5. Predict how many orders will remain pending after this batch\n\n",
            "Respond with valid JSON only."
        ])
        
        return "".join(prompt_parts)
    
    def _parse_gpt_response(self, response_text: str, order_data: Dict[str, Any]) -> GPTRecommendation:
        """Parse and validate GPT's JSON response"""
        
        try:
            # Extract JSON from response
            response_text = response_text.strip()
            if response_text.startswith("```json"):
                response_text = response_text[7:-3].strip()
            elif response_text.startswith("```"):
                response_text = response_text[3:-3].strip()
            
            data = json.loads(response_text)
            
            # Validate required fields
            required_fields = ["recommended_orders", "reasoning", "confidence"]
            for field in required_fields:
                if field not in data:
                    raise ValueError(f"Missing required field: {field}")
            
            # Validate order IDs exist in candidates
            candidate_ids = {order["order_id"] for order in order_data.get("candidate_orders", [])}
            recommended = data["recommended_orders"]
            
            # Log detailed comparison for debugging
            logger.info(f"🔍 CANDIDATE IDs: {sorted(candidate_ids)}")
            logger.info(f"🤖 GPT RECOMMENDED: {recommended}")
            
            # Filter out any recommended orders not in candidates
            valid_recommended = [oid for oid in recommended if oid in candidate_ids]
            invalid_recommended = [oid for oid in recommended if oid not in candidate_ids]
            
            if len(valid_recommended) != len(recommended):
                logger.warning(f"🚨 GPT recommended non-candidate orders: {invalid_recommended}")
                logger.warning(f"✅ Valid recommendations after filtering: {valid_recommended}")
                
            if not valid_recommended:
                logger.error(f"🚨 CRITICAL: No valid recommendations after filtering! GPT recommended {recommended} but candidates were {sorted(candidate_ids)}")
            
            deferred = data.get("deferred_orders", [])
            valid_deferred = [oid for oid in deferred if oid in candidate_ids]
            
            return GPTRecommendation(
                recommended_orders=valid_recommended,
                deferred_orders=valid_deferred,
                reasoning=data["reasoning"],
                confidence=min(1.0, max(0.0, float(data["confidence"]))),
                expected_pending=int(data.get("expected_pending", 0)),
                analysis_time=0.0  # Will be set by caller
            )
            
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.error(f"Failed to parse GPT response: {str(e)}\nResponse: {response_text}")
            raise Exception(f"Invalid GPT response format: {str(e)}")
    
    def _convert_orders_to_requirements(self, order_ids: List[str]) -> List[Dict]:
        """Convert order IDs to order requirements format for the optimizer"""
        order_requirements = []
        
        for order_id in order_ids:
            # Only use UUID lookup
            order = None
            try:
                import uuid
                uuid_obj = uuid.UUID(order_id)
                order = self.db.query(models.OrderMaster).filter(
                    models.OrderMaster.id == uuid_obj
                ).first()
            except (ValueError, TypeError):
                logger.warning(f"❌ Invalid UUID format in requirements conversion: {order_id}")
                continue
            
            if order:
                order_items = self.db.query(models.OrderItem).filter(
                    models.OrderItem.order_id == order.id
                ).all()
                
                for item in order_items:
                    # Get paper details from the relationship
                    paper = item.paper if hasattr(item, 'paper') and item.paper else None
                    if not paper:
                        paper = self.db.query(models.PaperMaster).filter(
                            models.PaperMaster.id == item.paper_id
                        ).first()
                    
                    order_requirements.append({
                        'width': float(item.width_inches),
                        'quantity': item.quantity_rolls,
                        'gsm': paper.gsm if paper else 80,  # Default GSM if not found
                        'bf': float(paper.bf) if paper else 1.0,  # Default BF if not found
                        'shade': paper.shade if paper else "White",  # Default shade if not found
                        'order_id': str(order.id),  # Always use UUID as string
                        'client_name': order.client.company_name if order.client else "Unknown"
                    })
        
        return order_requirements