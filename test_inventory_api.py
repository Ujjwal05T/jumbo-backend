#!/usr/bin/env python3
"""
Simple test script to verify inventory items API endpoints
"""

import sys
import os
import requests
import json

# Add the app directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

def test_api_endpoints():
    """Test the inventory items API endpoints"""
    base_url = "http://localhost:8000/api/inventory-items"
    
    print("Testing Inventory Items API...")
    print("=" * 50)
    
    # Test 1: Get inventory items
    print("1. Testing GET /api/inventory-items/")
    try:
        response = requests.get(f"{base_url}/", timeout=10)
        print(f"   Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   Total Items: {data.get('total', 'N/A')}")
            print(f"   Items in Response: {len(data.get('items', []))}")
        else:
            print(f"   Error: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"   Connection Error: {e}")
    
    print()
    
    # Test 2: Get statistics
    print("2. Testing GET /api/inventory-items/stats")
    try:
        response = requests.get(f"{base_url}/stats", timeout=10)
        print(f"   Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   Total Items: {data.get('total_items', 'N/A')}")
            print(f"   Total Weight: {data.get('total_weight_kg', 'N/A')} kg")
        else:
            print(f"   Error: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"   Connection Error: {e}")
    
    print()
    
    # Test 3: Get filter options
    print("3. Testing GET /api/inventory-items/filters")
    try:
        response = requests.get(f"{base_url}/filters", timeout=10)
        print(f"   Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   GSM Options: {len(data.get('gsm_options', []))}")
            print(f"   BF Options: {len(data.get('bf_options', []))}")
            print(f"   Grade Options: {len(data.get('grade_options', []))}")
        else:
            print(f"   Error: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"   Connection Error: {e}")
    
    print()
    
    # Test 4: Test with filters
    print("4. Testing GET /api/inventory-items/ with filters")
    try:
        params = {"page": 1, "per_page": 10, "gsm": 100}
        response = requests.get(f"{base_url}/", params=params, timeout=10)
        print(f"   Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   Filtered Items: {len(data.get('items', []))}")
            print(f"   Total Matching: {data.get('total', 'N/A')}")
        else:
            print(f"   Error: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"   Connection Error: {e}")
    
    print()
    print("=" * 50)
    print("API Test Complete")

if __name__ == "__main__":
    test_api_endpoints()