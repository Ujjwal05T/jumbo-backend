#!/usr/bin/env python3
"""
Test script to verify the API endpoints work after fixing the parameter issues.
"""

import requests
import json

BASE_URL = "http://localhost:8000/api"

def test_cutting_optimization_from_specs():
    """Test the /cutting-optimization/from-specs endpoint."""
    print("Testing /cutting-optimization/from-specs endpoint...")
    
    test_request = {
        "rolls": [
            {
                "width": 32,
                "quantity": 3,
                "gsm": 90,
                "bf": 18.0,
                "shade": "white",
                "min_length": 1000
            },
            {
                "width": 38,
                "quantity": 2,
                "gsm": 90,
                "bf": 18.0,
                "shade": "white",
                "min_length": 1000
            },
            {
                "width": 46,
                "quantity": 1,
                "gsm": 90,
                "bf": 18.0,
                "shade": "white",
                "min_length": 1000
            }
        ],
        "jumbo_roll_width": 118,
        "consider_standard_sizes": True,
        "strict_matching": True
    }
    
    try:
        response = requests.post(f"{BASE_URL}/cutting-optimization/from-specs", json=test_request)
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Success! Cutting optimization from specs:")
            print(f"   Total Rolls Needed: {result.get('total_rolls_needed', 0)}")
            print(f"   Total Waste Percentage: {result.get('total_waste_percentage', 0)}%")
            print(f"   Total Waste Inches: {result.get('total_waste_inches', 0)}\"")
            print(f"   Patterns Generated: {len(result.get('patterns', []))}")
            
            for i, pattern in enumerate(result.get('patterns', []), 1):
                rolls = pattern.get('rolls', [])
                widths = [roll.get('width', 0) for roll in rolls]
                print(f"   Pattern {i}: {widths} → Waste: {pattern.get('waste_inches', 0)}\"")
            
            if result.get('unfulfilled_orders'):
                print(f"   Unfulfilled Orders: {len(result['unfulfilled_orders'])}")
            
            return True
        else:
            print(f"❌ Failed with status {response.status_code}: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_cutting_optimization_validate():
    """Test the /cutting-optimization/validate-plan endpoint."""
    print("\nTesting /cutting-optimization/validate-plan endpoint...")
    
    test_plan = {
        "patterns": [
            {
                "rolls": [
                    {"width": 32, "gsm": 90, "bf": 18.0, "shade": "white"},
                    {"width": 38, "gsm": 90, "bf": 18.0, "shade": "white"}
                ],
                "waste_percentage": 5.2,
                "waste_inches": 6.0
            }
        ],
        "requirements": [
            {"width": 32, "quantity": 1, "gsm": 90, "bf": 18.0, "shade": "white"},
            {"width": 38, "quantity": 1, "gsm": 90, "bf": 18.0, "shade": "white"}
        ]
    }
    
    try:
        response = requests.post(f"{BASE_URL}/cutting-optimization/validate-plan", json=test_plan)
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Success! Plan validation:")
            print(f"   Valid: {result.get('valid', False)}")
            print(f"   Issues: {len(result.get('issues', []))}")
            print(f"   Recommendations: {len(result.get('recommendations', []))}")
            
            for issue in result.get('issues', []):
                print(f"   ⚠️ Issue: {issue}")
            
            for rec in result.get('recommendations', []):
                print(f"   💡 Recommendation: {rec}")
            
            return True
        else:
            print(f"❌ Failed with status {response.status_code}: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    """Main test function."""
    print("🔧 TESTING API ENDPOINTS AFTER PARAMETER FIX")
    print("=" * 60)
    
    success_count = 0
    total_tests = 2
    
    # Test 1: from-specs endpoint
    if test_cutting_optimization_from_specs():
        success_count += 1
    
    # Test 2: validate-plan endpoint  
    if test_cutting_optimization_validate():
        success_count += 1
    
    print("\n" + "=" * 60)
    print(f"✅ TESTS COMPLETED: {success_count}/{total_tests} passed")
    
    if success_count == total_tests:
        print("🎉 All API endpoints are working correctly!")
    else:
        print("⚠️ Some tests failed. Check the server logs for details.")

if __name__ == "__main__":
    main()