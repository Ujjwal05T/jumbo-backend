#!/usr/bin/env python3
"""
Test script to verify database query fixes work correctly.
"""

import requests
import json

BASE_URL = "http://localhost:8000/api"

def test_basic_endpoints():
    """Test basic endpoints that were causing MSSQL errors."""
    print("🔧 Testing Database Query Fixes")
    print("=" * 50)
    
    endpoints_to_test = [
        ("GET", "/orders", "Orders list"),
        ("GET", "/jumbo-rolls", "Jumbo rolls list"),
        ("GET", "/cut-rolls", "Cut rolls list"),
        ("GET", "/pending-items", "Pending items list"),
        ("GET", "/production-orders", "Production orders list"),
        ("GET", "/cutting-plans", "Cutting plans list"),
    ]
    
    success_count = 0
    
    for method, endpoint, description in endpoints_to_test:
        print(f"\n{description}...")
        try:
            if method == "GET":
                response = requests.get(f"{BASE_URL}{endpoint}?limit=5")
            
            if response.status_code == 200:
                print(f"✅ {description}: SUCCESS")
                success_count += 1
            else:
                print(f"❌ {description}: FAILED - {response.status_code}")
                print(f"   Error: {response.text[:100]}...")
        except Exception as e:
            print(f"❌ {description}: ERROR - {str(e)}")
    
    print(f"\n📊 Results: {success_count}/{len(endpoints_to_test)} endpoints working")
    return success_count == len(endpoints_to_test)

def test_order_creation():
    """Test creating an order (this was the original failing operation)."""
    print(f"\n" + "=" * 50)
    print("🎯 Testing Order Creation (Original Issue)")
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
            print(f"   Customer: {order.get('customer_name')}")
            print(f"   Specification: {order.get('width_inches')}\" x {order.get('quantity_rolls')} rolls")
            return True
        else:
            print(f"❌ Order creation: FAILED - {response.status_code}")
            print(f"   Error: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Order creation: ERROR - {str(e)}")
        return False

def test_database_health():
    """Test database health endpoint."""
    print(f"\n" + "=" * 50)
    print("🏥 Testing Database Health")
    print("=" * 50)
    
    try:
        response = requests.get(f"{BASE_URL}/status")
        
        if response.status_code == 200:
            status = response.json()
            print("✅ Database health: SUCCESS")
            print(f"   Status: {status.get('status')}")
            print(f"   Database: {status.get('database')}")
            return True
        else:
            print(f"❌ Database health: FAILED - {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Database health: ERROR - {str(e)}")
        return False

def main():
    """Main test function."""
    print("🚀 TESTING DATABASE QUERY FIXES")
    print("=" * 60)
    print("Testing fixes for:")
    print("• MSSQL OFFSET/LIMIT requires ORDER BY")
    print("• SQLAlchemy is_(None) method issues")
    print("• Column reference corrections")
    print("=" * 60)
    
    # Test basic endpoints
    endpoints_ok = test_basic_endpoints()
    
    # Test order creation (original failing operation)
    order_creation_ok = test_order_creation()
    
    # Test database health
    db_health_ok = test_database_health()
    
    print("\n" + "=" * 60)
    print("📋 SUMMARY")
    print("=" * 60)
    
    if endpoints_ok and order_creation_ok and db_health_ok:
        print("🎉 ALL TESTS PASSED!")
        print("✅ MSSQL OFFSET/LIMIT issues fixed")
        print("✅ SQLAlchemy column references fixed")
        print("✅ Database queries working correctly")
        print("\nThe system is now ready for use!")
    else:
        print("⚠️ SOME TESTS FAILED")
        if not endpoints_ok:
            print("❌ Basic endpoint queries need attention")
        if not order_creation_ok:
            print("❌ Order creation still has issues")
        if not db_health_ok:
            print("❌ Database connection problems")
        print("\nCheck the server logs for detailed error information.")

if __name__ == "__main__":
    main()