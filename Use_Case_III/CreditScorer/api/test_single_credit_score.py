#!/usr/bin/env python3

import asyncio
import aiohttp
import json

async def test_single_credit_score():
    """Test a single credit score request to isolate the issue"""
    
    base_url = "http://localhost:8000"
    test_user_data = {
        "username": "testuser123",
        "email": "test123@example.com",
        "password": "testpass123"
    }
    
    example_data = {
        "data": [{
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
        }]
    }

    async with aiohttp.ClientSession() as session:
        # First, get API key
        login_data = {
            "username": test_user_data["username"],
            "password": test_user_data["password"],
            "name": "test-key"
        }
        
        async with session.post(f"{base_url}/auth/generate-key", json=login_data) as response:
            login_result = await response.json()
            if response.status != 200:
                print(f"Login failed: {login_result}")
                return
            
            api_key = login_result.get('api_key')
            if not api_key:
                print("No API key received")
                return
            
            print(f"Got API key: {api_key[:20]}...")
        
        # Now test credit-scores endpoint
        headers = {"Authorization": f"Bearer {api_key}"}
        
        print("Testing credit-scores endpoint...")
        async with session.post(f"{base_url}/api/credit-scores", json=example_data, headers=headers) as response:
            print(f"Status: {response.status}")
            try:
                result = await response.json()
                print(f"Response: {json.dumps(result, indent=2)}")
            except Exception as e:
                text = await response.text()
                print(f"Response text: {text}")
                print(f"Error parsing JSON: {e}")

if __name__ == "__main__":
    asyncio.run(test_single_credit_score())