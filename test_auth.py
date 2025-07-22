"""
Test script for authentication functionality.
Run this script to test the authentication endpoints.
"""
import requests
import base64
import json
from datetime import datetime

# Configuration
BASE_URL = "http://localhost:8000/api"
TEST_USERNAME = "testuser"
TEST_PASSWORD = "testpassword"

def basic_auth_header(username, password):
    """Create HTTP Basic Auth header value"""
    auth_str = f"{username}:{password}"
    auth_bytes = auth_str.encode("utf-8")
    auth_b64 = base64.b64encode(auth_bytes).decode("utf-8")
    return f"Basic {auth_b64}"

def test_create_user():
    """Test creating a user"""
    print("\n=== Testing User Creation ===")
    
    # First, try to login with admin credentials to create a user
    admin_auth = basic_auth_header("admin", "admin")
    
    # Create test user
    user_data = {
        "username": TEST_USERNAME,
        "password": TEST_PASSWORD,
        "role": "operator"
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/users/",
            headers={"Authorization": admin_auth},
            json=user_data
        )
        
        if response.status_code == 200:
            print(f"✅ User created successfully: {response.json()}")
            return True
        elif response.status_code == 400 and "already registered" in response.json().get("detail", ""):
            print(f"ℹ️ User already exists")
            return True
        else:
            print(f"❌ Failed to create user: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error creating user: {str(e)}")
        return False

def test_login():
    """Test login endpoint"""
    print("\n=== Testing Login ===")
    
    auth_header = basic_auth_header(TEST_USERNAME, TEST_PASSWORD)
    
    try:
        response = requests.post(
            f"{BASE_URL}/auth/login",
            headers={"Authorization": auth_header}
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Login successful: {data['username']}")
            print(f"   Session token: {data['session_token']}")
            print(f"   Expires at: {data['expires_at']}")
            return data["session_token"]
        else:
            print(f"❌ Login failed: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ Error during login: {str(e)}")
        return None

def test_me_endpoint(session_token=None):
    """Test /auth/me endpoint with session token or basic auth"""
    print("\n=== Testing /auth/me Endpoint ===")
    
    headers = {}
    auth_type = "session token" if session_token else "basic auth"
    
    if session_token:
        headers["Authorization"] = f"Bearer {session_token}"
    else:
        headers["Authorization"] = basic_auth_header(TEST_USERNAME, TEST_PASSWORD)
    
    try:
        response = requests.get(
            f"{BASE_URL}/auth/me",
            headers=headers
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ /auth/me with {auth_type} successful: {data['username']}")
            return True
        else:
            print(f"❌ /auth/me with {auth_type} failed: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error accessing /auth/me with {auth_type}: {str(e)}")
        return False

def test_session_check(session_token):
    """Test session-check endpoint"""
    print("\n=== Testing Session Check ===")
    
    if not session_token:
        print("❌ No session token available")
        return False
    
    try:
        response = requests.get(
            f"{BASE_URL}/auth/session-check",
            headers={"Authorization": f"Bearer {session_token}"}
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Session check successful: {data}")
            return True
        else:
            print(f"❌ Session check failed: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error checking session: {str(e)}")
        return False

def test_logout(session_token=None):
    """Test logout endpoint"""
    print("\n=== Testing Logout ===")
    
    headers = {}
    auth_type = "session token" if session_token else "basic auth"
    
    if session_token:
        headers["Authorization"] = f"Bearer {session_token}"
    else:
        headers["Authorization"] = basic_auth_header(TEST_USERNAME, TEST_PASSWORD)
    
    try:
        response = requests.post(
            f"{BASE_URL}/auth/logout",
            headers=headers
        )
        
        if response.status_code == 200:
            print(f"✅ Logout with {auth_type} successful")
            return True
        else:
            print(f"❌ Logout with {auth_type} failed: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error during logout with {auth_type}: {str(e)}")
        return False

def test_session_after_logout(session_token):
    """Test session after logout"""
    print("\n=== Testing Session After Logout ===")
    
    if not session_token:
        print("❌ No session token available")
        return
    
    try:
        response = requests.get(
            f"{BASE_URL}/auth/session-check",
            headers={"Authorization": f"Bearer {session_token}"}
        )
        
        if response.status_code == 401:
            print(f"✅ Session correctly invalidated after logout")
        else:
            print(f"❌ Session still valid after logout: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error checking session after logout: {str(e)}")

def run_tests():
    """Run all tests"""
    print("=== Authentication System Tests ===")
    print(f"Testing against API at {BASE_URL}")
    print(f"Test user: {TEST_USERNAME}")
    
    # Create test user if needed
    if not test_create_user():
        print("❌ Cannot proceed with tests without a valid user")
        return
    
    # Test login
    session_token = test_login()
    
    # Test /auth/me with basic auth
    test_me_endpoint()
    
    # Test /auth/me with session token
    if session_token:
        test_me_endpoint(session_token)
        
        # Test session check
        test_session_check(session_token)
        
        # Test logout with session token
        test_logout(session_token)
        
        # Test session after logout
        test_session_after_logout(session_token)
    
    # Test logout with basic auth
    test_logout()
    
    print("\n=== Tests Complete ===")

if __name__ == "__main__":
    run_tests()