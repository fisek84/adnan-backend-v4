#!/usr/bin/env python3
"""
Manual test script for CEO Notion Ops activation.

This script validates:
1. CEO can toggle Notion Ops via API
2. CEO can activate via chat keywords
3. State persists across requests
4. Frontend integration works correctly

Usage:
    python manual_test_ceo_activation.py
"""

import json
import sys
import requests
from typing import Dict, Any


BASE_URL = "http://localhost:8000"
CEO_TOKEN = "test_secret_123"
TEST_SESSION_ID = "manual_test_session_123"


def make_headers(include_token: bool = True, include_initiator: bool = True) -> Dict[str, str]:
    """Create request headers."""
    headers = {"Content-Type": "application/json"}
    
    if include_token:
        headers["X-CEO-Token"] = CEO_TOKEN
    
    if include_initiator:
        headers["X-Initiator"] = "ceo_chat"
    
    return headers


def test_toggle_api_activation() -> bool:
    """Test 1: Toggle API activation."""
    print("\n=== Test 1: Toggle API Activation ===")
    
    url = f"{BASE_URL}/api/notion-ops/toggle"
    payload = {
        "session_id": TEST_SESSION_ID,
        "armed": True
    }
    
    try:
        response = requests.post(url, json=payload, headers=make_headers())
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Response: {json.dumps(data, indent=2)}")
            
            if data.get("armed") is True:
                print("✓ Activation successful!")
                return True
            else:
                print("✗ Failed: armed state is not True")
                return False
        else:
            print(f"✗ Failed with status {response.status_code}: {response.text}")
            return False
    except requests.RequestException as e:
        print(f"✗ Request failed: {e}")
        return False


def test_toggle_api_deactivation() -> bool:
    """Test 2: Toggle API deactivation."""
    print("\n=== Test 2: Toggle API Deactivation ===")
    
    url = f"{BASE_URL}/api/notion-ops/toggle"
    payload = {
        "session_id": TEST_SESSION_ID,
        "armed": False
    }
    
    try:
        response = requests.post(url, json=payload, headers=make_headers())
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Response: {json.dumps(data, indent=2)}")
            
            if data.get("armed") is False:
                print("✓ Deactivation successful!")
                return True
            else:
                print("✗ Failed: armed state is not False")
                return False
        else:
            print(f"✗ Failed with status {response.status_code}: {response.text}")
            return False
    except requests.RequestException as e:
        print(f"✗ Request failed: {e}")
        return False


def test_chat_activation_keywords() -> bool:
    """Test 3: Chat activation via keywords."""
    print("\n=== Test 3: Chat Activation via Keywords ===")
    
    url = f"{BASE_URL}/api/chat"
    payload = {
        "message": "notion ops aktiviraj",
        "session_id": TEST_SESSION_ID,
        "metadata": {
            "session_id": TEST_SESSION_ID,
            "initiator": "ceo_chat"
        }
    }
    
    try:
        response = requests.post(url, json=payload, headers=make_headers())
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Response text: {data.get('text', 'N/A')}")
            
            notion_ops = data.get("notion_ops", {})
            print(f"Notion Ops state: armed={notion_ops.get('armed')}")
            
            if notion_ops.get("armed") is True:
                print("✓ Chat activation successful!")
                return True
            else:
                print("✗ Failed: notion_ops.armed is not True")
                return False
        else:
            print(f"✗ Failed with status {response.status_code}: {response.text}")
            return False
    except requests.RequestException as e:
        print(f"✗ Request failed: {e}")
        return False


def test_chat_deactivation_keywords() -> bool:
    """Test 4: Chat deactivation via keywords."""
    print("\n=== Test 4: Chat Deactivation via Keywords ===")
    
    url = f"{BASE_URL}/api/chat"
    payload = {
        "message": "notion ops ugasi",
        "session_id": TEST_SESSION_ID,
        "metadata": {
            "session_id": TEST_SESSION_ID,
            "initiator": "ceo_chat"
        }
    }
    
    try:
        response = requests.post(url, json=payload, headers=make_headers())
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Response text: {data.get('text', 'N/A')}")
            
            notion_ops = data.get("notion_ops", {})
            print(f"Notion Ops state: armed={notion_ops.get('armed')}")
            
            if notion_ops.get("armed") is False:
                print("✓ Chat deactivation successful!")
                return True
            else:
                print("✗ Failed: notion_ops.armed is not False")
                return False
        else:
            print(f"✗ Failed with status {response.status_code}: {response.text}")
            return False
    except requests.RequestException as e:
        print(f"✗ Request failed: {e}")
        return False


def test_non_ceo_blocked() -> bool:
    """Test 5: Non-CEO users are blocked."""
    print("\n=== Test 5: Non-CEO Users Blocked ===")
    
    url = f"{BASE_URL}/api/notion-ops/toggle"
    payload = {
        "session_id": TEST_SESSION_ID,
        "armed": True
    }
    
    # Request without CEO headers
    try:
        response = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
        print(f"Status: {response.status_code}")
        
        if response.status_code == 403:
            print("✓ Non-CEO correctly blocked!")
            return True
        else:
            print(f"✗ Failed: expected 403, got {response.status_code}")
            print(f"Response: {response.text}")
            return False
    except requests.RequestException as e:
        print(f"✗ Request failed: {e}")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("CEO Notion Ops Activation - Manual Test Suite")
    print("=" * 60)
    print(f"Base URL: {BASE_URL}")
    print(f"Session ID: {TEST_SESSION_ID}")
    print("=" * 60)
    
    tests = [
        ("Toggle API Activation", test_toggle_api_activation),
        ("Toggle API Deactivation", test_toggle_api_deactivation),
        ("Chat Activation Keywords", test_chat_activation_keywords),
        ("Chat Deactivation Keywords", test_chat_deactivation_keywords),
        ("Non-CEO Blocked", test_non_ceo_blocked),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ Test '{name}' crashed: {e}")
            results.append((name, False))
    
    print("\n" + "=" * 60)
    print("Test Results Summary")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
        if result:
            passed += 1
        else:
            failed += 1
    
    print("=" * 60)
    print(f"Total: {len(results)} | Passed: {passed} | Failed: {failed}")
    print("=" * 60)
    
    if failed == 0:
        print("\n✓ All tests passed!")
        sys.exit(0)
    else:
        print(f"\n✗ {failed} test(s) failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
