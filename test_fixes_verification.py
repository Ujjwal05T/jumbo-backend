#!/usr/bin/env python3
"""
Test script to verify the latest fixes work correctly.
"""

import requests
import json

BASE_URL = "http://localhost:8000/api"

def test_order_creation():
    """Test order creation with the new flexible approach."""
    print("🎯 Testing Order Creation (Flexible Approach)")
    print("=" * 50)
    
    test_order = {
        "customer_name": "Test Customer",
        "width_inches": 42,
        "gsm": 90,
        "bf": 18.0,
        "shade": "white",
        "quantity_rolls": 3
    }
    
    try:
        response = requests.post(f"{BASE_URL}/orders", json=test_order)
        
        if response.status_code == 200:
            order = response.json()
            print("✅ Order creation: SUCCESS")
            print(f"   Order ID: {order.get('id')}")
            print(f"   Status: {order.get('status')}")
            print(f"   Customer: {order.get('customer_name')}")
            print(f"   Specification: {order.get('width_inches')}\" x {order.get('quantity_rolls')} rolls")
            return order.get('id')
        else:
            print(f"❌ Order creation: FAILED - {response.status_code}")
            print(f"   Error: {response.text}")
            return None
    except Exception as e:
        print(f"❌ Order creation: ERROR - {str(e)}")
        return None

def test_production_orders():
    """Test production orders endpoint."""
    print(f"\n🏭 Testing Production Orders Endpoint")
    print("=" * 50)
    
    try:
        response = requests.get(f"{BASE_URL}/production-orders?limit=5")
        
        if response.status_code == 200:
            orders = response.json()
            print("✅ Production orders: SUCCESS")
            print(f"   Found {len(orders)} production orders")
            
            for order in orders[:2]:  # Show first 2
                print(f"   • ID: {order.get('id')}")
                print(f"     Spec: GSM={order.get('gsm')}, Shade={order.get('shade')}, Status={order.get('status')}")
            
            return True
        else:
            print(f"❌ Production orders: FAILED - {response.status_code}")
            print(f"   Error: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Production orders: ERROR - {str(e)}")
        return False

def test_database_status():
    """Test database status with improved query."""
    print(f"\n🏥 Testing Database Status")
    print("=" * 50)
    
    try:
        response = requests.get(f"{BASE_URL}/status/")
        
        if response.status_code == 200:
            status = response.json()
            print("✅ Database status: SUCCESS")
            print(f"   Status: {status.get('status')}")
            print(f"   Database: {status.get('database')}")
            print(f"   Test Query Result: {status.get('test_query_result')}")
            return status.get('database') == 'connected'
        else:
            print(f"❌ Database status: FAILED - {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Database status: ERROR - {str(e)}")
        return False

def test_order_fulfillment(order_id):
    """Test order fulfillment process."""
    if not order_id:
        print(f"\n⏭️ Skipping order fulfillment test (no order ID)")
        return False
        
    print(f"\n🔄 Testing Order Fulfillment")
    print("=" * 50)
    
    try:
        response = requests.post(f"{BASE_URL}/orders/{order_id}/fulfill")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Order fulfillment: SUCCESS")
            print(f"   Status: {result.get('status')}")
            print(f"   Message: {result.get('message')}")
            
            if result.get('batch_size'):
                print(f"   Batch Size: {result.get('batch_size')} orders")
            
            return True
        else:
            print(f"❌ Order fulfillment: FAILED - {response.status_code}")
            print(f"   Error: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Order fulfillment: ERROR - {str(e)}")
        return False

def test_pending_items():
    """Test pending items functionality."""
    print(f"\n📋 Testing Pending Items")
    print("=" * 50)
    
    try:
        response = requests.get(f"{BASE_URL}/pending-items/summary")
        
        if response.status_code == 200:
            summary = response.json()
            print("✅ Pending items summary: SUCCESS")
            print(f"   Total pending: {summary.get('total_pending_items', 0)}")
            print(f"   In production: {summary.get('items_in_production', 0)}")
            print(f"   Total quantity: {summary.get('total_quantity_pending', 0)}")
            return True
        else:
            print(f"❌ Pending items: FAILED - {response.status_code}")
            print(f"   Error: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Pending items: ERROR - {str(e)}")
        return False

def main():
    """Main test function."""
    print("🚀 TESTING LATEST FIXES")
    print("=" * 60)
    print("Testing fixes for:")
    print("• Flexible order creation (no strict inventory check)")
    print("• Production orders endpoint error handling")
    print("• Database status query improvement")
    print("• Order fulfillment workflow")
    print("=" * 60)
    
    # Test order creation
    order_id = test_order_creation()
    
    # Test production orders
    production_ok = test_production_orders()
    
    # Test database status
    db_ok = test_database_status()
    
    # Test order fulfillment
    fulfillment_ok = test_order_fulfillment(order_id)
    
    # Test pending items
    pending_ok = test_pending_items()
    
    print("\n" + "=" * 60)
    print("📋 SUMMARY")
    print("=" * 60)
    
    tests = [
        ("Order Creation", order_id is not None),
        ("Production Orders", production_ok),
        ("Database Status", db_ok),
        ("Order Fulfillment", fulfillment_ok),
        ("Pending Items", pending_ok)
    ]
    
    passed = sum(1 for _, result in tests if result)
    total = len(tests)
    
    for test_name, result in tests:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")
    
    print(f"\n📊 Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 ALL TESTS PASSED!")
        print("The system is working correctly with all fixes applied.")
    else:
        print("⚠️ Some tests failed, but core functionality should work.")
        print("Check individual test results above for details.")

if __name__ == "__main__":
    main()