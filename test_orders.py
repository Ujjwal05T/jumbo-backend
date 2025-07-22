"""
Test script for order management functionality.
Run this script to test the order endpoints.
"""
import requests
import base64
import json
from datetime import datetime
import uuid

# Configuration
BASE_URL = "http://localhost:8000/api"
TEST_USERNAME = "admin"
TEST_PASSWORD = "admin"

def basic_auth_header(username, password):
    """Create HTTP Basic Auth header value"""
    auth_str = f"{username}:{password}"
    auth_bytes = auth_str.encode("utf-8")
    auth_b64 = base64.b64encode(auth_bytes).decode("utf-8")
    return f"Basic {auth_b64}"

def test_create_order():
    """Test creating an order"""
    print("\n=== Testing Order Creation ===")
    
    auth_header = basic_auth_header(TEST_USERNAME, TEST_PASSWORD)
    
    # Create test order
    order_data = {
        "customer_name": "Test Customer",
        "width_inches": 55,
        "gsm": 160,
        "bf": 90.5,
        "shade": "White",
        "quantity_rolls": 3,
        "quantity_tons": 1.5
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/orders/",
            headers={"Authorization": auth_header},
            json=order_data
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Order created successfully: {data}")
            return data["id"]
        else:
            print(f"❌ Failed to create order: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ Error creating order: {str(e)}")
        return None

def test_get_orders():
    """Test getting orders with filtering"""
    print("\n=== Testing Get Orders with Filtering ===")
    
    auth_header = basic_auth_header(TEST_USERNAME, TEST_PASSWORD)
    
    try:
        # Test without filters
        response = requests.get(
            f"{BASE_URL}/orders/",
            headers={"Authorization": auth_header}
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Got {len(data)} orders without filters")
        else:
            print(f"❌ Failed to get orders: {response.status_code} - {response.text}")
        
        # Test with filters
        response = requests.get(
            f"{BASE_URL}/orders/?customer_name=Test&width_inches=55",
            headers={"Authorization": auth_header}
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Got {len(data)} orders with filters")
        else:
            print(f"❌ Failed to get filtered orders: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"❌ Error getting orders: {str(e)}")

def test_get_order_by_id(order_id):
    """Test getting an order by ID"""
    print("\n=== Testing Get Order by ID ===")
    
    if not order_id:
        print("❌ No order ID provided")
        return
    
    auth_header = basic_auth_header(TEST_USERNAME, TEST_PASSWORD)
    
    try:
        response = requests.get(
            f"{BASE_URL}/orders/{order_id}",
            headers={"Authorization": auth_header}
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Got order by ID: {data}")
        else:
            print(f"❌ Failed to get order: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"❌ Error getting order: {str(e)}")

def test_get_order_details(order_id):
    """Test getting order details"""
    print("\n=== Testing Get Order Details ===")
    
    if not order_id:
        print("❌ No order ID provided")
        return
    
    auth_header = basic_auth_header(TEST_USERNAME, TEST_PASSWORD)
    
    try:
        response = requests.get(
            f"{BASE_URL}/orders/{order_id}/details",
            headers={"Authorization": auth_header}
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Got order details: {data}")
        else:
            print(f"❌ Failed to get order details: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"❌ Error getting order details: {str(e)}")

def test_update_order(order_id):
    """Test updating an order"""
    print("\n=== Testing Update Order ===")
    
    if not order_id:
        print("❌ No order ID provided")
        return
    
    auth_header = basic_auth_header(TEST_USERNAME, TEST_PASSWORD)
    
    # Update order status
    update_data = {
        "status": "processing"
    }
    
    try:
        response = requests.put(
            f"{BASE_URL}/orders/{order_id}",
            headers={"Authorization": auth_header},
            json=update_data
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Order updated successfully: {data}")
        else:
            print(f"❌ Failed to update order: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"❌ Error updating order: {str(e)}")

def test_get_orders_by_status():
    """Test getting orders by status"""
    print("\n=== Testing Get Orders by Status ===")
    
    auth_header = basic_auth_header(TEST_USERNAME, TEST_PASSWORD)
    
    try:
        response = requests.get(
            f"{BASE_URL}/orders/status/processing",
            headers={"Authorization": auth_header}
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Got {len(data)} orders with status 'processing'")
        else:
            print(f"❌ Failed to get orders by status: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"❌ Error getting orders by status: {str(e)}")

def test_delete_order(order_id):
    """Test deleting an order"""
    print("\n=== Testing Delete Order ===")
    
    if not order_id:
        print("❌ No order ID provided")
        return
    
    auth_header = basic_auth_header(TEST_USERNAME, TEST_PASSWORD)
    
    try:
        response = requests.delete(
            f"{BASE_URL}/orders/{order_id}",
            headers={"Authorization": auth_header}
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Order deleted successfully: {data}")
        else:
            print(f"❌ Failed to delete order: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"❌ Error deleting order: {str(e)}")

def run_tests():
    """Run all tests"""
    print("=== Order Management Tests ===")
    print(f"Testing against API at {BASE_URL}")
    
    # Create test order
    order_id = test_create_order()
    
    # Get orders with filtering
    test_get_orders()
    
    if order_id:
        # Get order by ID
        test_get_order_by_id(order_id)
        
        # Get order details
        test_get_order_details(order_id)
        
        # Update order
        test_update_order(order_id)
        
        # Get orders by status
        test_get_orders_by_status()
        
        # Delete order
        test_delete_order(order_id)
    
    print("\n=== Tests Complete ===")

if __name__ == "__main__":
    run_tests()