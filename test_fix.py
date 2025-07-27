#!/usr/bin/env python3
"""
Quick test script to verify the fix for OrderMaster paper relationship issue
"""

import sys
import os

# Add the app directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.database import SessionLocal
from app import crud
import uuid

def test_orders_with_paper_specs():
    """Test the fixed get_orders_with_paper_specs function"""
    db = SessionLocal()
    try:
        # Get a few order IDs from the database
        from app.models import OrderMaster
        orders = db.query(OrderMaster).limit(3).all()
        
        if not orders:
            print("No orders found in database. Please create some test orders first.")
            return
        
        order_ids = [order.id for order in orders]
        print(f"Testing with order IDs: {[str(id) for id in order_ids]}")
        
        # Test the function
        try:
            result = crud.get_orders_with_paper_specs(db, order_ids)
            print(f"✅ Success! Found {len(result)} order requirements")
            
            if result:
                print("Sample order requirement:")
                print(f"  - Order ID: {result[0]['order_id']}")
                print(f"  - Width: {result[0]['width']}\"")
                print(f"  - Quantity: {result[0]['quantity']}")
                print(f"  - Paper: {result[0]['gsm']}gsm, {result[0]['bf']}bf, {result[0]['shade']}")
                print(f"  - Client: {result[0]['client_name']}")
            
        except Exception as e:
            print(f"❌ Error: {e}")
            return False
            
    finally:
        db.close()
    
    return True

if __name__ == "__main__":
    print("Testing OrderMaster paper relationship fix...")
    success = test_orders_with_paper_specs()
    if success:
        print("✅ Test passed! The fix is working correctly.")
    else:
        print("❌ Test failed. Please check the implementation.")