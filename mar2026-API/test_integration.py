#!/usr/bin/env python3
"""
Integration test with REAL AWS services
Requires valid AWS credentials and existing DynamoDB tables
 
Run: python test_integration.py <profile_id>
Example: python test_integration.py user123
"""
 
import json
import os
import sys
 
# Add the current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
 
# Ensure environment variables are loaded
from dotenv import load_dotenv
load_dotenv()
 
from main import lambda_handler
 
 
class MockLambdaContext:
    """Mock AWS Lambda context"""
    def __init__(self):
        self.function_name = "candi-ai-api"
        self.memory_limit_in_mb = 512
        self.invoked_function_arn = "arn:aws:lambda:us-east-1:123456789:function:candi-ai-api"
        self.aws_request_id = "integration-test"
 
 
def test_with_real_aws(profile_id):
    """Test with actual AWS DynamoDB and Gemini API"""
    print("="*60)
    print("INTEGRATION TEST - REAL AWS SERVICES")
    print("="*60)
    print(f"Profile ID: {profile_id}")
    print("="*60)
 
    # Test health check first
    print("\n--- Health Check ---")
    event = {"path": "/"}
    context = MockLambdaContext()
    response = lambda_handler(event, context)
    print(f"Status: {response['statusCode']}")
    print(f"Body: {response['body']}")
 
    if response['statusCode'] != 200:
        print("❌ Health check failed! Check AWS credentials.")
        return
 
    # Test main AI endpoint
    print("\n--- Main AI Analysis ---")
    event = {"uid": profile_id}
    response = lambda_handler(event, context)
    print(f"Status: {response['statusCode']}")
 
    if response['statusCode'] == 200:
        body = json.loads(response['body'])
        print("\nAnalysis Result:")
        # profile_id removido da resposta intencionalmente (LGPD 3.4 — minimização de dados)
        print(f"  Entries Analyzed: {body['entries_analyzed']}")
        print(f"  Timestamp: {body['timestamp']}")
        print("\nAI Analysis (structured JSON):")
        print(json.dumps(body['ai_analysis'], indent=2, ensure_ascii=False))
    else:
        print(f"Error: {response['body']}")
 
 
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_integration.py <profile_id>")
        print("Example: python test_integration.py user123")
        sys.exit(1)
 
    profile_id = sys.argv[1]
    test_with_real_aws(profile_id)
 