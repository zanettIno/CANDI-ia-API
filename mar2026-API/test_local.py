#!/usr/bin/env python3
"""
Local testing script for CANDI Lambda API
Run: python test_local.py

This script tests the lambda_handler locally without deploying to AWS.
"""

import json
import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

# Add the current directory to path so we can import main
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Mock environment variables BEFORE importing main
os.environ.setdefault("CHAVE_API", "your-gemini-api-key-here")
os.environ.setdefault("aws_ACCESS_KEY_ID", "test-key")
os.environ.setdefault("aws_SECRET_ACCESS_KEY", "test-secret")
os.environ.setdefault("aws_REGION", "us-east-1")

# Now import main
from main import lambda_handler, convert_to_ai_format, generate_ai_insight


class MockLambdaContext:
    """Mock AWS Lambda context object"""
    def __init__(self):
        self.function_name = "candi-ai-api"
        self.memory_limit_in_mb = 512
        self.invoked_function_arn = "arn:aws:lambda:us-east-1:123456789:function:candi-ai-api"
        self.aws_request_id = "local-test-" + datetime.now().strftime("%Y%m%d%H%M%S")


def test_health_check():
    """Test the health check endpoint"""
    print("\n" + "="*60)
    print("TEST 1: Health Check Endpoint")
    print("="*60)

    event = {"path": "/"}
    context = MockLambdaContext()

    response = lambda_handler(event, context)
    print(f"Status Code: {response['statusCode']}")
    print(f"Response Body:")
    print(json.dumps(json.loads(response['body']), indent=2, ensure_ascii=False))


def test_convert_to_ai_format():
    """Test the data formatting function"""
    print("\n" + "="*60)
    print("TEST 2: Data Formatting (convert_to_ai_format)")
    print("="*60)

    # Mock data simulating DynamoDB items
    sentimentos_data = [
        {
            "created_at": "2026-03-25T14:30:00Z",
            "happiness": 2,
            "observation": "Dia difícil no trabalho, muitas reuniões"
        },
        {
            "created_at": "2026-03-26T09:00:00Z",
            "happiness": 4,
            "observation": "Consegui terminar aquele projeto"
        },
        {
            "created_at": "2026-03-27T20:00:00Z",
            "happiness": 3,
            "observation": ""
        }
    ]

    sintomas_data = [
        {
            "created_at": "2026-03-25T14:30:00Z",
            "description": "Dor de cabeça leve"
        },
        {
            "created_at": "2026-03-26T09:00:00Z",
            "description": "Cansaço ao acordar"
        }
    ]

    result = convert_to_ai_format(sentimentos_data, sintomas_data)
    print("Structured Data for AI:")
    print(json.dumps(result, indent=2, ensure_ascii=False))

    return result


def test_generate_ai_insight():
    """Test the Gemini AI integration"""
    print("\n" + "="*60)
    print("TEST 3: AI Insight Generation (calls Gemini API)")
    print("="*60)

    test_data = {
        "paciente": {
            "total_registros_sentimentos": 2,
            "total_registros_sintomas": 1,
            "periodo_analisado": "últimos registros"
        },
        "sentimentos": [
            {
                "data_registro": "2026-03-25T14:30:00Z",
                "nivel_felicidade_numerico": 2,
                "sentimento_label": "Triste",
                "emoji": "😟",
                "gravidade_emocional": "medium",
                "classificacao_sentimento": "negativo",
                "observacao": "Dia difícil no trabalho"
            },
            {
                "data_registro": "2026-03-26T09:00:00Z",
                "nivel_felicidade_numerico": 4,
                "sentimento_label": "Feliz",
                "emoji": "😊",
                "gravidade_emocional": "low",
                "classificacao_sentimento": "positivo",
                "observacao": "Consegui terminar o projeto"
            }
        ],
        "sintomas": [
            {
                "data_registro": "2026-03-25T14:30:00Z",
                "descricao": "Dor de cabeça leve"
            }
        ]
    }

    try:
        result = generate_ai_insight(test_data)
        print("AI Response:")
        print(result)

        # Try to parse as JSON
        try:
            parsed = json.loads(result)
            print("\n✅ Successfully parsed AI response as JSON!")
            print("\nStructured AI Response:")
            print(json.dumps(parsed, indent=2, ensure_ascii=False))
        except json.JSONDecodeError:
            print("\n⚠️  AI response is not valid JSON (raw text above)")

    except Exception as e:
        print(f"❌ Error calling Gemini API: {e}")
        print("Make sure your CHAVE_API environment variable is set correctly!")


def test_full_flow_mocked():
    """Test full Lambda flow with mocked DynamoDB"""
    print("\n" + "="*60)
    print("TEST 4: Full Lambda Flow (with mocked DynamoDB)")
    print("="*60)

    # Mock DynamoDB responses
    mock_sentimentos = [
        {
            "created_at": "2026-03-27T10:00:00Z",
            "happiness": 3,
            "observation": "Dia normal"
        }
    ]
    mock_sintomas = [
        {
            "created_at": "2026-03-27T10:00:00Z",
            "description": "Nenhum sintoma relatado"
        }
    ]

    # Patch the table scan methods
    with patch('main.sentimentos_tabela') as mock_sent_table, \
         patch('main.sintomas_tabela') as mock_sint_table:

        mock_sent_table.scan.return_value = {"Items": mock_sentimentos}
        mock_sint_table.scan.return_value = {"Items": mock_sintomas}
        mock_sent_table.name = "CANDIFeelings"
        mock_sint_table.name = "CANDISymptoms"

        event = {"uid": "test-user-123"}
        context = MockLambdaContext()

        response = lambda_handler(event, context)
        print(f"Status Code: {response['statusCode']}")
        print(f"Response Body:")
        try:
            body = json.loads(response['body'])
            print(json.dumps(body, indent=2, ensure_ascii=False))
        except:
            print(response['body'])


def test_error_cases():
    """Test error handling"""
    print("\n" + "="*60)
    print("TEST 5: Error Cases")
    print("="*60)

    # Test missing profile_id
    print("\n--- Missing profile_id ---")
    event = {"path": "/analyze"}  # No uid or profile_id
    context = MockLambdaContext()
    response = lambda_handler(event, context)
    print(f"Status: {response['statusCode']}")
    print(f"Body: {response['body']}")

    # Test no data found (with mocked empty tables)
    print("\n--- No data found ---")
    with patch('main.sentimentos_tabela') as mock_sent_table, \
         patch('main.sintomas_tabela') as mock_sint_table:

        mock_sent_table.scan.return_value = {"Items": []}
        mock_sint_table.scan.return_value = {"Items": []}
        mock_sent_table.name = "CANDIFeelings"
        mock_sint_table.name = "CANDISymptoms"

        event = {"uid": "user-with-no-data"}
        response = lambda_handler(event, context)
        print(f"Status: {response['statusCode']}")
        print(f"Body: {response['body']}")


def run_all_tests():
    """Run all tests in sequence"""
    print("\n" + "="*60)
    print("CANDI API LOCAL TEST SUITE")
    print("="*60)

    try:
        test_health_check()
    except Exception as e:
        print(f"❌ Health check test failed: {e}")

    try:
        test_convert_to_ai_format()
    except Exception as e:
        print(f"❌ Data formatting test failed: {e}")

    try:
        test_generate_ai_insight()
    except Exception as e:
        print(f"❌ AI insight test failed: {e}")

    try:
        test_full_flow_mocked()
    except Exception as e:
        print(f"❌ Full flow test failed: {e}")

    try:
        test_error_cases()
    except Exception as e:
        print(f"❌ Error cases test failed: {e}")

    print("\n" + "="*60)
    print("TEST SUITE COMPLETE")
    print("="*60)


if __name__ == "__main__":
    # Check if specific test requested
    if len(sys.argv) > 1:
        test_name = sys.argv[1]
        if test_name == "health":
            test_health_check()
        elif test_name == "format":
            test_convert_to_ai_format()
        elif test_name == "ai":
            test_generate_ai_insight()
        elif test_name == "full":
            test_full_flow_mocked()
        elif test_name == "errors":
            test_error_cases()
        else:
            print(f"Unknown test: {test_name}")
            print("Available tests: health, format, ai, full, errors")
    else:
        run_all_tests()
