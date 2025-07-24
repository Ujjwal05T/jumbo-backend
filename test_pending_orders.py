#!/usr/bin/env python3
"""
Test script to verify pending order functionality works after migration.
"""

import requests
import json

BASE_URL = "http://localhost:8000/api"

def test_pending_items_endpoints():
    """Test the new pending items endpoints."""
    print("🔍 Testing Pending Order Endpoints")
    print("=" * 50)
    
    # Test 1: Get pending items summary
    print("\n1. Testing pending items summary...")
    try:
        response = requests.get(f"{BASE_URL}/pending-items/summary")
        if response.status_code == 200:
            summary = response.json()
            print("✅ Pending items summary:")
            print(f"   Total pending items: {summary.get('total_pending_items', 0)}")
            print(f"   Items in production: {summary.get('items_in_production', 0)}")
            print(f"   Total quantity pending: {summary.get('total_quantity_pending', 0)}")
            print(f"   Unique specifications: {summary.get('unique_specifications', 0)}")
            print(f"   Consolidation opportunities: {summary.get('consolidation_opportunities', 0)}")
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")
    
    # Test 2: Get consolidation opportunities
    print("\n2. Testing consolidation opportunities...")
    try:
        response = requests.get(f"{BASE_URL}/pending-items/consolidation-opportunities")
        if response.status_code == 200:
            opportunities = response.json()
            print(f"✅ Found {opportunities.get('total_opportunities', 0)} consolidation opportunities")
            
            for i, opp in enumerate(opportunities.get('consolidation_opportunities', []), 1):
                spec = opp['specification']
                print(f"   {i}. GSM={spec['gsm']}, Shade={spec['shade']}, BF={spec['bf']}")
                print(f"      Items: {opp['item_count']}, Quantity: {opp['total_quantity']}, Priority: {opp['priority']}")
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")
    
    # Test 3: Get pending items list
    print("\n3. Testing pending items list...")
    try:
        response = requests.get(f"{BASE_URL}/pending-items?limit=10")
        if response.status_code == 200:
            result = response.json()
            items = result.get('pending_items', [])
            print(f"✅ Found {len(items)} pending items")
            
            for item in items[:3]:  # Show first 3
                spec = item['specification']
                print(f"   • {spec['width']}\" x {item['quantity_pending']} rolls")
                print(f"     GSM={spec['gsm']}, Shade={spec['shade']}, Status={item['status']}")
        else:
            print(f"❌ Failed: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")

def test_workflow_with_pending_tracking():
    """Test creating an order and see if pending items are tracked."""
    print("\n" + "=" * 50)
    print("🔄 Testing Workflow with Pending Tracking")
    print("=" * 50)
    
    # Create a test order
    print("\n1. Creating test order...")
    test_order = {
        "customer_name": "Test Customer",
        "width_inches": 55,  # Unusual width to likely create pending items
        "gsm": 95,           # Unusual GSM
        "bf": 19.5,          # Unusual BF
        "shade": "cream",    # Unusual shade
        "quantity_rolls": 8  # Large quantity
    }
    
    try:
        response = requests.post(f"{BASE_URL}/orders", json=test_order)
        if response.status_code == 200:
            order = response.json()
            order_id = order['id']
            print(f"✅ Created order {order_id}")
            
            # Try to fulfill the order (should create pending items)
            print("\n2. Attempting to fulfill order...")
            response = requests.post(f"{BASE_URL}/orders/{order_id}/fulfill")
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Fulfillment result: {result.get('status')}")
                print(f"   Message: {result.get('message')}")
                
                # Check if pending items were created
                print("\n3. Checking for new pending items...")
                response = requests.get(f"{BASE_URL}/pending-items?limit=5")
                if response.status_code == 200:
                    result = response.json()
                    items = result.get('pending_items', [])
                    new_items = [item for item in items if item['specification']['gsm'] == 95]
                    
                    if new_items:
                        print(f"✅ Found {len(new_items)} new pending items for our test order")
                        for item in new_items:
                            print(f"   • {item['specification']['width']}\" x {item['quantity_pending']} rolls")
                            print(f"     Reason: {item['reason']}, Status: {item['status']}")
                    else:
                        print("ℹ️ No new pending items found (order may have been fulfilled from inventory)")
                else:
                    print(f"❌ Failed to check pending items: {response.text}")
            else:
                print(f"❌ Failed to fulfill order: {response.text}")
        else:
            print(f"❌ Failed to create order: {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")

def main():
    """Main test function."""
    print("🚀 TESTING PENDING ORDER FUNCTIONALITY")
    print("=" * 60)
    
    # Test the endpoints
    test_pending_items_endpoints()
    
    # Test the workflow
    test_workflow_with_pending_tracking()
    
    print("\n" + "=" * 60)
    print("✅ PENDING ORDER TESTS COMPLETED")
    print("=" * 60)
    print("\nIf all tests passed, the pending order system is working correctly!")
    print("You can now:")
    print("• Track pending items in the database")
    print("• Get consolidation opportunities")
    print("• Monitor pending item status")
    print("• Link pending items to production orders")

if __name__ == "__main__":
    main()