#!/usr/bin/env python3
"""
Test script for validating the complete wastage integration flow:
1. Planning phase: Query wastage_inventory → Match with orders → Reduce order quantities
2. Execution phase: Convert wastage allocations to InventoryMaster cut rolls
"""
import sys
import os
sys.path.append('D:\\JumboReelApp\\backend')

from app.database import get_db
from app import models
from app.services.plan_calculation_service import PlanCalculationService
from app.services.cutting_optimizer import CuttingOptimizer
from sqlalchemy.orm import Session
import uuid
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_wastage_flow():
    """Test the complete wastage integration flow"""

    # Get database session
    db_gen = get_db()
    db = next(db_gen)

    try:
        logger.info("=" * 60)
        logger.info("🧪 TESTING WASTAGE INTEGRATION FLOW")
        logger.info("=" * 60)

        # STEP 1: Check available wastage in wastage_inventory
        logger.info("\n📋 STEP 1: Checking available wastage inventory")
        available_wastage = db.query(models.WastageInventory).filter(
            models.WastageInventory.status == models.WastageStatus.AVAILABLE.value
        ).all()

        logger.info(f"Found {len(available_wastage)} available wastage rolls:")
        for w in available_wastage[:5]:  # Show first 5
            logger.info(f"  - {w.frontend_id}: {w.width_inches}\" x {w.weight_kg}kg, Paper: {w.paper_id}, Status: {w.status}")

        # Also check if any have weight > 0
        wastage_with_weight = [w for w in available_wastage if w.weight_kg and w.weight_kg > 0]
        logger.info(f"Wastage with weight > 0: {len(wastage_with_weight)}")

        # Create a test wastage roll with meaningful weight for testing
        if not wastage_with_weight:
            logger.info("📝 Creating test wastage roll for demonstration...")
            paper = db.query(models.PaperMaster).first()
            if paper:
                test_wastage = models.WastageInventory(
                    width_inches=20.0,
                    paper_id=paper.id,
                    weight_kg=100.0,  # 100kg test weight
                    status=models.WastageStatus.AVAILABLE.value,
                    frontend_id="TEST-WS-001"
                )
                db.add(test_wastage)
                db.commit()
                db.refresh(test_wastage)
                logger.info(f"✅ Created test wastage: {test_wastage.frontend_id} - 20.0\" x 100kg")
                available_wastage.append(test_wastage)

        # STEP 2: Check pending orders that might match wastage
        logger.info("\n📋 STEP 2: Checking orders for wastage matching")
        orders = db.query(models.OrderMaster).filter(
            models.OrderMaster.status.in_(["created", "pending"])
        ).limit(3).all()

        logger.info(f"Found {len(orders)} orders for testing:")
        order_ids = []
        for order in orders:
            logger.info(f"  - Order {order.frontend_id}: {len(order.order_items)} items")
            order_ids.append(order.id)

            for item in order.order_items:
                logger.info(f"    * {item.width_inches}\" x {item.quantity_kg}kg, Paper: {item.paper_id}")

        if not order_ids:
            logger.warning("❌ No orders found for testing")
            return

        # STEP 3: Test the plan calculation with wastage allocation
        logger.info("\n📋 STEP 3: Testing plan calculation with wastage allocation")
        calculation_service = PlanCalculationService(db, jumbo_roll_width=118)

        calculation_result = calculation_service.calculate_plan_for_orders(
            order_ids=order_ids,
            include_pending_orders=True,
            include_available_inventory=True
        )

        wastage_allocations = calculation_result.get('wastage_allocations', [])
        logger.info(f"✅ CALCULATION COMPLETE: Found {len(wastage_allocations)} wastage allocations")

        for allocation in wastage_allocations:
            logger.info(f"  - Allocation: Wastage {allocation.get('wastage_frontend_id')} → Order {allocation.get('order_id')}")

        # STEP 4: Test plan creation with wastage allocations
        logger.info("\n📋 STEP 4: Testing plan creation with wastage data")
        if calculation_result.get('cut_rolls_generated') or wastage_allocations:
            optimizer = CuttingOptimizer(jumbo_roll_width=118)

            # Create a test user if needed
            test_user = db.query(models.UserMaster).first()
            if not test_user:
                logger.warning("❌ No user found for testing")
                return

            # Create plan using the optimizer (which now uses PlanCalculationService)
            plan = optimizer.create_plan_from_orders(
                db=db,
                order_ids=order_ids,
                created_by_id=test_user.id,
                plan_name="Test Wastage Plan",
                interactive=False
            )

            logger.info(f"✅ PLAN CREATED: {plan.frontend_id}")

            # Check if wastage allocations are stored in cut_pattern
            import json
            try:
                cut_pattern_data = json.loads(plan.cut_pattern) if isinstance(plan.cut_pattern, str) else plan.cut_pattern
                stored_wastage = cut_pattern_data.get('wastage_allocations', [])
                logger.info(f"📦 PLAN DATA: {len(stored_wastage)} wastage allocations stored in plan")
            except:
                logger.warning("⚠️ Could not parse plan cut_pattern data")

            logger.info(f"✅ TESTING COMPLETE: Plan {plan.frontend_id} created successfully")

        else:
            logger.info("ℹ️ No optimization results to create plan from")

    except Exception as e:
        logger.error(f"❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()

    finally:
        db.close()

if __name__ == "__main__":
    test_wastage_flow()