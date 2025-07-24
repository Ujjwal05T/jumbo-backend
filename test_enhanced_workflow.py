#!/usr/bin/env python3
"""
Test script to demonstrate the enhanced workflow with pending order consolidation.
"""

import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:8000/api"

def create_test_orders():
    """Create test orders with some matching specifications."""
    
    orders = [
        # Group 1: GSM=90, Shade=white, BF=18.0 (should be consolidated)
        {
            "customer_name": "Customer A",
            "width_inches": 32,
            "gsm": 90,
            "bf": 18.0,
            "shade": "white",
            "quantity_rolls": 3
        },
        {
            "customer_name": "Customer B", 
            "width_inches": 38,
            "gsm": 90,
            "bf": 18.0,
            "shade": "white",
            "quantity_rolls": 2
        },
        {
            "customer_name": "Customer C",
            "width_inches": 46,
            "gsm": 90,
            "bf": 18.0,
            "shade": "white",
            "quantity_rolls": 1
        },
        
        # Group 2: GSM=120, Shade=blue, BF=20.0 (should be consolidated)
        {
            "customer_name": "Customer D",
            "width_inches": 35,
            "gsm": 120,
            "bf": 20.0,
            "shade": "blue",
            "quantity_rolls": 4
        },
        {
            "customer_name": "Customer E",
            "width_inches": 42,
            "gsm": 120,
            "bf": 20.0,
            "shade": "blue",
            "quantity_rolls": 2
        },
        
        # Single order (different spec)
        {
            "customer_name": "Customer F",
            "width_inches": 48,
            "gsm": 80,
            "bf": 16.0,
            "shade": "yellow",
            "quantity_rolls": 5
        }
    ]
    
    created_orders = []
    print("Creating test orders...")
    
    for order in orders:
        try:
            response = requests.post(f"{BASE_URL}/orders", json=order)
            if response.status_code == 200:
                created_order = response.json()
                created_orders.append(created_order)
                print(f"✅ Created order {created_order['id']}: {order['customer_name']} - {order['width_inches']}\" x {order['quantity_rolls']} rolls")
            else:
                print(f"❌ Failed to create order for {order['customer_name']}: {response.text}")
        except Exception as e:
            print(f"❌ Error creating order: {e}")
    
    return created_orders

def test_consolidation_opportunities():
    """Test the consolidation opportunities endpoint."""
    print("\n" + "="*60)
    print("TESTING CONSOLIDATION OPPORTUNITIES")
    print("="*60)
    
    try:
        response = requests.get(f"{BASE_URL}/orders/consolidation-opportunities")
        if response.status_code == 200:
            opportunities = response.json()
            print(f"Found {opportunities['total_groups']} consolidation opportunities:")
            
            for i, opp in enumerate(opportunities['consolidation_opportunities'], 1):
                spec = opp['specification']
                print(f"\n{i}. Specification: GSM={spec['gsm']}, Shade={spec['shade']}, BF={spec['bf']}")
                print(f"   Orders: {opp['order_count']}, Total Quantity: {opp['total_quantity']}")
                print(f"   Potential Savings: {opp['potential_savings']}")
                print(f"   Order IDs: {', '.join(opp['order_ids'][:3])}{'...' if len(opp['order_ids']) > 3 else ''}")
            
            return opportunities
        else:
            print(f"❌ Failed to get consolidation opportunities: {response.text}")
            return None
    except Exception as e:
        print(f"❌ Error getting consolidation opportunities: {e}")
        return None

def test_single_order_fulfillment(order_id):
    """Test fulfilling a single order (should trigger consolidation)."""
    print(f"\n" + "="*60)
    print(f"TESTING SINGLE ORDER FULFILLMENT WITH AUTO-CONSOLIDATION")
    print("="*60)
    
    try:
        response = requests.post(f"{BASE_URL}/orders/{order_id}/fulfill")
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Order fulfillment result:")
            print(f"   Status: {result.get('status')}")
            print(f"   Message: {result.get('message')}")
            if result.get('batch_size'):
                print(f"   🎯 Batch Size: {result['batch_size']} orders processed together")
                print(f"   📋 Cutting Plans Created: {result.get('cutting_plans_created', 0)}")
                print(f"   🏭 Production Orders Created: {result.get('production_orders_created', 0)}")
            return result
        else:
            print(f"❌ Failed to fulfill order: {response.text}")
            return None
    except Exception as e:
        print(f"❌ Error fulfilling order: {e}")
        return None

def test_batch_processing(order_ids):
    """Test batch processing of multiple orders."""
    print(f"\n" + "="*60)
    print(f"TESTING BATCH PROCESSING")
    print("="*60)
    
    try:
        response = requests.post(f"{BASE_URL}/workflow/process-orders", json=order_ids)
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Batch processing result:")
            summary = result.get('summary', {})
            print(f"   Orders Processed: {summary.get('orders_processed', 0)}")
            print(f"   Orders Completed: {summary.get('orders_completed', 0)}")
            print(f"   Orders Partially Fulfilled: {summary.get('orders_partially_fulfilled', 0)}")
            print(f"   Cutting Plans Created: {summary.get('cutting_plans_created', 0)}")
            print(f"   Production Orders Created: {summary.get('production_orders_created', 0)}")
            print(f"   Total Jumbos Used: {summary.get('total_jumbos_used', 0)}")
            print(f"   Overall Waste: {summary.get('overall_waste_percentage', 0)}%")
            print(f"   Total Trim: {summary.get('total_trim_inches', 0)}\"")
            
            if result.get('next_steps'):
                print(f"\n📋 Next Steps:")
                for step in result['next_steps']:
                    print(f"   • {step}")
            
            return result
        else:
            print(f"❌ Failed to process batch: {response.text}")
            return None
    except Exception as e:
        print(f"❌ Error processing batch: {e}")
        return None

def test_workflow_status():
    """Test workflow status endpoint."""
    print(f"\n" + "="*60)
    print(f"TESTING WORKFLOW STATUS")
    print("="*60)
    
    try:
        response = requests.get(f"{BASE_URL}/workflow/status")
        if response.status_code == 200:
            status = response.json()
            print(f"📊 Workflow Status:")
            
            orders = status.get('orders', {})
            print(f"   Orders - Pending: {orders.get('pending', 0)}, Partial: {orders.get('partially_fulfilled', 0)}")
            
            cutting = status.get('cutting_plans', {})
            print(f"   Cutting Plans - Ready: {cutting.get('ready_to_execute', 0)}")
            
            production = status.get('production', {})
            print(f"   Production - Pending: {production.get('pending_orders', 0)}")
            
            inventory = status.get('inventory', {})
            print(f"   Inventory - Available Jumbos: {inventory.get('available_jumbo_rolls', 0)}")
            
            if status.get('recommendations'):
                print(f"\n💡 Recommendations:")
                for rec in status['recommendations']:
                    print(f"   • {rec}")
            
            return status
        else:
            print(f"❌ Failed to get workflow status: {response.text}")
            return None
    except Exception as e:
        print(f"❌ Error getting workflow status: {e}")
        return None

def main():
    """Main test function."""
    print("🚀 ENHANCED WORKFLOW TEST WITH PENDING ORDER CONSOLIDATION")
    print("="*80)
    
    # Step 1: Create test orders
    created_orders = create_test_orders()
    if not created_orders:
        print("❌ Failed to create test orders. Exiting.")
        return
    
    # Step 2: Check consolidation opportunities
    opportunities = test_consolidation_opportunities()
    
    # Step 3: Test single order fulfillment (should auto-consolidate)
    if created_orders:
        first_order_id = created_orders[0]['id']
        test_single_order_fulfillment(first_order_id)
    
    # Step 4: Test batch processing
    if len(created_orders) >= 3:
        batch_order_ids = [order['id'] for order in created_orders[1:4]]  # Skip first order
        test_batch_processing(batch_order_ids)
    
    # Step 5: Check final workflow status
    test_workflow_status()
    
    print(f"\n" + "="*80)
    print("✅ ENHANCED WORKFLOW TEST COMPLETED")
    print("="*80)
    print("\nKey Features Demonstrated:")
    print("• ✅ Automatic pending order consolidation")
    print("• ✅ Specification-based grouping")
    print("• ✅ Batch processing optimization")
    print("• ✅ Waste minimization through consolidation")
    print("• ✅ Production order creation for pending items")
    print("• ✅ Complete workflow status tracking")

if __name__ == "__main__":
    main()