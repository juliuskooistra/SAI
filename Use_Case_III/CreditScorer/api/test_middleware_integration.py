"""
Comprehensive test suite for the middleware integration system.
Tests authentication, rate limiting, and billing middlewares.
"""

import asyncio
import json
from typing import Dict, Any
import aiohttp


class APITestSuite:
    """Test suite for the complete middleware stack."""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.session = None
        self.test_user_data = {
            "username": "testuser123",
            "email": "test123@example.com", 
            "password": "testpass123"
        }
        self.api_key = None
        self.user_id = None
        self.example_data = {
            "data": [
                {
                    "loan_amnt": 6500,
                    "term": 60,
                    "int_rate": 0.14649999,
                    "installment": 153.4499969482422,
                    "grade": "C",
                    "sub_grade": "C3",
                    "emp_title": "Other",
                    "emp_length": "5 years",
                    "home_ownership": "OWN",
                    "annual_inc": 72000.0,
                    "verification_status": "Not Verified",
                    "issue_d": 1322697600000,
                    "purpose": "debt_consolidation",
                    "title": "Other",
                    "zip_code": "853xx",
                    "addr_state": "AZ",
                    "dti": 16.1200008392334,
                    "delinq_2yrs": 0,
                    "earliest_cr_line": 883612800000,
                    "fico_range_low": 695,
                    "fico_range_high": 699,
                    "inq_last_6mths": 2,
                    "mths_since_last_delinq": 31,
                    "mths_since_last_record": 73,
                    "open_acc": 14,
                    "pub_rec": 0,
                    "revol_bal": 4032,
                    "revol_util": 0.206,
                    "total_acc": 23,
                    "term_months": 60,
                    "emp_length_years": 5.0,
                    "fico_mid": 697.0,
                    "credit_hist_months": 166.9513797634691,
                    "income_to_loan": 11.076923076923077,
                    "revol_util_ratio": 0.00206,
                    "dti_bucket": "medium",
                    "zip3": "853",
                    "region": "Other",
                    "target_default": "0"
                },
                {
                    "loan_amnt": 10000,
                    "term": 36,
                    "int_rate": 0.1065,
                    "installment": 325.739990234375,
                    "grade": "B",
                    "sub_grade": "B2",
                    "emp_title": "Other",
                    "emp_length": "3 years",
                    "home_ownership": "RENT",
                    "annual_inc": 100000.0,
                    "verification_status": "Source Verified",
                    "issue_d": 1322697600000,
                    "purpose": "other",
                    "title": "Other",
                    "zip_code": "Other",
                    "addr_state": "CA",
                    "dti": 7.059999942779541,
                    "delinq_2yrs": 0,
                    "earliest_cr_line": 673056000000,
                    "fico_range_low": 720,
                    "fico_range_high": 724,
                    "inq_last_6mths": 2,
                    "mths_since_last_delinq": 31,
                    "mths_since_last_record": 73,
                    "open_acc": 14,
                    "pub_rec": 0,
                    "revol_bal": 11997,
                    "revol_util": 0.555,
                    "total_acc": 29,
                    "term_months": 36,
                    "emp_length_years": 3.0,
                    "fico_mid": 722.0,
                    "credit_hist_months": 247.01051248357425,
                    "income_to_loan": 10.0,
                    "revol_util_ratio": 0.00555,
                    "dti_bucket": "low",
                    "zip3": "Other",
                    "region": "West",
                    "target_default": "1"
                }
            ],
        }
        self.portfolio_data = {
            "budget": 5000.0,
            "note_size": 100.0,
            "max_weight": 0.05,
            "min_loans": 20,
            "grade_cap": 0.5,
            "state_cap": None
        }
    
    async def setup_session(self):
        """Setup HTTP session for testing."""
        self.session = aiohttp.ClientSession()
    
    async def cleanup_session(self):
        """Cleanup HTTP session."""
        if self.session:
            await self.session.close()
    
    async def make_request(self, method: str, endpoint: str, headers: Dict = None, 
                          json_data: Dict = None, params: Dict = None) -> Dict[str, Any]:
        """Make HTTP request and return response data."""
        url = f"{self.base_url}{endpoint}"
        headers = headers or {}
        
        try:
            async with self.session.request(
                method=method,
                url=url,
                headers=headers,
                json=json_data,
                params=params
            ) as response:
                try:
                    response_data = await response.json()
                except:
                    response_data = {"text": await response.text()}
                
                return {
                    "status": response.status,
                    "headers": dict(response.headers),
                    "data": response_data
                }
        except Exception as e:
            return {
                "status": 0,
                "headers": {},
                "data": {"error": str(e)}
            }
    
    async def test_1_user_registration(self):
        """Test 1: User registration (no middleware protection)."""
        print("\n🧪 Test 1: User Registration")
        print("-" * 50)
        
        response = await self.make_request(
            "POST", 
            "/auth/register",
            json_data=self.test_user_data
        )
        
        print(f"Status: {response['status']}")
        print(f"Response: {json.dumps(response['data'], indent=2)}")
        
        if response['status'] == 200:
            self.user_id = response['data'].get('user_id')
            print("✅ Registration successful")
            return True
        elif response['status'] == 400 and "already exists" in str(response['data']):
            print("⚠️  User already exists, continuing...")
            return True
        else:
            print("❌ Registration failed")
            return False
    
    async def test_2_user_login(self):
        """Test 2: User login (no middleware protection)."""
        print("\n🧪 Test 2: User Login")
        print("-" * 50)
        
        login_data = {
            "username": self.test_user_data["username"],
            "password": self.test_user_data["password"]
        }
        
        response = await self.make_request(
            "POST",
            "/auth/login", 
            json_data=login_data
        )
        
        print(f"Status: {response['status']}")
        print(f"Response: {json.dumps(response['data'], indent=2)}")
        
        if response['status'] == 200:
            print("✅ Login successful")
            self.user_id = response['data'].get('user_id')
            return True
        else:
            print("❌ Login failed")
            return False
    
    async def test_3_api_key_generation(self):
        """Test 3: API key generation (authentication middleware only)."""
        print("\n🧪 Test 3: API Key Generation")
        print("-" * 50)
        
        # First login to get credentials
        login_data = {
            "username": self.test_user_data["username"],
            "password": self.test_user_data["password"],
            "name": "test-key"
        }
        
        login_response = await self.make_request(
            "POST",
            "/auth/generate-key",
            json_data=login_data
        )
        
        if login_response['status'] != 200:
            print("❌ Login failed before API key generation")
            return False
        
        # Get temporary access token from login
        access_token = login_response['data'].get('api_key')
        if not access_token:
            print("❌ No access token received")
            return False

        self.api_key = access_token
        print(f"✅ API key generated: {self.api_key[:20]}...")
        return True

    
    async def test_4_balance_check(self):
        """Test 4: Check balance (authentication middleware only)."""
        print("\n🧪 Test 4: Balance Check")
        print("-" * 50)
        
        if not self.api_key:
            print("❌ No API key available")
            return False

        headers = {"Authorization": f"Bearer {self.api_key}"}

        response = await self.make_request(
            "GET",
            "/billing/balance",
            headers=headers
        )
        
        print(f"Status: {response['status']}")
        print(f"Response: {json.dumps(response['data'], indent=2)}")
        
        if response['status'] == 200:
            balance = response['data'].get('current_balance', 0)
            print(f"✅ Current balance: {balance} tokens")
            return True
        else:
            print("❌ Balance check failed")
            return False
    
    async def test_5_unauthenticated_api_access(self):
        """Test 5: Try to access API without authentication."""
        print("\n🧪 Test 5: Unauthenticated API Access")
        print("-" * 50)
        
        response = await self.make_request(
            "GET",
            "/api/credit-scores"
        )
        
        print(f"Status: {response['status']}")
        print(f"Response: {json.dumps(response['data'], indent=2)}")
        
        if response['status'] == 401:
            print("✅ Properly rejected unauthenticated request")
            return True
        else:
            print("❌ Should have rejected unauthenticated request")
            return False
    
    async def test_6_api_access_with_billing(self):
        """Test 6: Access API endpoint with full middleware stack."""
        print("\n🧪 Test 6: API Access with Billing")
        print("-" * 50)
        
        if not self.api_key:
            print("❌ No API key available")
            return False
        
        headers = {"Authorization": f"Bearer {self.api_key}"}
        
        response = await self.make_request(
            "POST",
            "/api/credit-scores",
            headers=headers,
            json_data=self.example_data
        )
        
        print(f"Status: {response['status']}")
        print(f"Response: {json.dumps(response['data'], indent=2)}")
        
        # Check billing headers
        billing_headers = {
            "X-Tokens-Consumed": response['headers'].get('x-tokens-consumed'),
            "X-Remaining-Balance": response['headers'].get('x-remaining-balance'),
            "X-Processing-Time-Ms": response['headers'].get('x-processing-time-ms')
        }
        print(f"Billing Headers: {billing_headers}")
        
        if response['status'] == 200:
            print("✅ API request successful with billing")
            return True
        elif response['status'] == 402:
            print("⚠️  Insufficient balance - this is expected behavior")
            return True
        else:
            print("❌ API request failed unexpectedly")
            return False
        
    async def test_6_5_api_access_portfolio(self):
        """Test 6.5: Access API endpoint with full middleware stack."""
        print("\n🧪 Test 6.5: API Access with Billing")
        print("-" * 50)
        
        if not self.api_key:
            print("❌ No API key available")
        
            return False
        headers = {"Authorization": f"Bearer {self.api_key}"}
        
        response = await self.make_request(
            "POST",
            "/api/optimize-portfolio",
            headers=headers,
            json_data=self.portfolio_data
        )
        
        print(f"Status: {response['status']}")
        print(f"Response: {json.dumps(response['data'], indent=2)}")
        
        # Check billing headers
        billing_headers = {
            "X-Tokens-Consumed": response['headers'].get('x-tokens-consumed'),
            "X-Remaining-Balance": response['headers'].get('x-remaining-balance'),
            "X-Processing-Time-Ms": response['headers'].get('x-processing-time-ms')
        }
        print(f"Billing Headers: {billing_headers}")
        
        if response['status'] == 200:
            print("✅ API request successful with billing")
            return True
        elif response['status'] == 402:
            print("⚠️  Insufficient balance - this is expected behavior")
            return True
        else:
            print("❌ API request failed unexpectedly")
            return False
    
    
    async def test_7_rate_limiting(self):
        """Test 7: Rate limiting functionality."""
        print("\n🧪 Test 7: Rate Limiting Test")
        print("-" * 50)
        
        if not self.api_key:
            print("❌ No API key available")
            return False
        
        headers = {"Authorization": f"Bearer {self.api_key}"}
        
        # Make multiple rapid requests to trigger rate limiting
        print("Making rapid requests to test rate limiting...")
        
        success_count = 0
        rate_limited_count = 0
        
        for i in range(15):  # Try 15 requests rapidly
            response = await self.make_request(
                "POST",
                "/api/credit-scores",
                headers=headers,
                json_data=self.example_data
            )
            
            if response['status'] == 200:
                success_count += 1
                print(f"Request {i+1}: ✅ Success")
            elif response['status'] == 429:
                rate_limited_count += 1
                print(f"Request {i+1}: ⚠️  Rate limited")
            elif response['status'] == 402:
                print(f"Request {i+1}: 💰 Insufficient balance")
                break
            else:
                print(f"Request {i+1}: ❌ Error {response['status']}")
            
            # Small delay between requests
            await asyncio.sleep(0.1)
        
        print(f"Results: {success_count} successful, {rate_limited_count} rate limited")
        
        if rate_limited_count > 0:
            print("✅ Rate limiting is working")
            return True
        else:
            print("⚠️  Rate limiting may not be triggered (depends on limits)")
            return True
    
    async def test_8_token_purchase(self):
        """Test 8: Token purchase (authentication only, no billing)."""
        print("\n🧪 Test 8: Token Purchase")
        print("-" * 50)
        
        if not self.api_key:
            print("❌ No API key available")
            return False
        
        headers = {"Authorization": f"Bearer {self.api_key}"}
        purchase_data = {
            "amount": 50.0,
            "payment_method": "test"
        }
        
        response = await self.make_request(
            "POST",
            "/billing/purchase-tokens",
            headers=headers,
            json_data=purchase_data
        )
        
        print(f"Status: {response['status']}")
        print(f"Response: {json.dumps(response['data'], indent=2)}")
        
        if response['status'] == 200:
            print("✅ Token purchase successful")
            return True
        else:
            print("❌ Token purchase failed")
            return False
    
    async def test_9_usage_history(self):
        """Test 9: Get usage history (authentication only)."""
        print("\n🧪 Test 9: Usage History")
        print("-" * 50)
        
        if not self.api_key:
            print("❌ No API key available")
            return False
        
        headers = {"Authorization": f"Bearer {self.api_key}"}
        
        response = await self.make_request(
            "GET",
            "/billing/usage-stats",
            headers=headers
        )
        
        print(f"Status: {response['status']}")
        print(f"Response: {json.dumps(response['data'], indent=2)}")
        
        if response['status'] == 200:
            usage_records = response['data'].get('endpoint_breakdown', [])
            print(f"✅ Found {len(usage_records)} endpoint with usage records")
            return True
        else:
            print("❌ Usage history failed")
            return False
    
    async def test_10_final_balance_check(self):
        """Test 10: Final balance check."""
        print("\n🧪 Test 10: Final Balance Check")
        print("-" * 50)
        
        if not self.api_key:
            print("❌ No API key available")
            return False
        
        headers = {"Authorization": f"Bearer {self.api_key}"}
        
        response = await self.make_request(
            "GET",
            "/billing/balance",
            headers=headers
        )
        
        print(f"Status: {response['status']}")
        print(f"Response: {json.dumps(response['data'], indent=2)}")
        
        if response['status'] == 200:
            balance = response['data'].get('current_balance', 0)
            total_used = response['data'].get('total_used', 0)
            print(f"✅ Final balance: {balance} tokens")
            print(f"✅ Total tokens used: {total_used} tokens")
            return True
        else:
            print("❌ Final balance check failed")
            return False
    
    async def run_all_tests(self):
        """Run all tests in sequence."""
        print("🚀 Starting Middleware Integration Test Suite")
        print("=" * 60)
        
        await self.setup_session()
        
        tests = [
            self.test_1_user_registration,
            self.test_2_user_login,
            self.test_3_api_key_generation,
            self.test_4_balance_check,
            self.test_5_unauthenticated_api_access,
            self.test_6_api_access_with_billing,
            self.test_6_5_api_access_portfolio,
            self.test_7_rate_limiting,
            self.test_8_token_purchase,
            self.test_9_usage_history,
            self.test_10_final_balance_check
        ]
        
        passed = 0
        total = len(tests)
        
        for test in tests:
            try:
                if await test():
                    passed += 1
                else:
                    print("❌ Test failed")
                
                # Small delay between tests
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"❌ Test error: {e}")
        
        await self.cleanup_session()
        
        print("\n" + "=" * 60)
        print(f"🏁 Test Results: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 All tests passed! Middleware integration is working correctly.")
        else:
            print("⚠️  Some tests failed. Check the output above for details.")
        
        return passed == total


async def main():
    """Main test runner."""
    # Check if server is running
    test_suite = APITestSuite()
    await test_suite.setup_session()
    
    try:
        health_check = await test_suite.make_request("GET", "/")
        if health_check['status'] == 0:
            print("❌ Server is not running. Please start the API server first:")
            print("   uvicorn main:app --reload")
            return
    except:
        print("❌ Cannot connect to server. Please start the API server first:")
        print("   uvicorn main:app --reload")
        return
    finally:
        await test_suite.cleanup_session()
    
    # Run the test suite
    test_suite = APITestSuite()
    await test_suite.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())