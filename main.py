from dotenv import load_dotenv
import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError
import requests
import json
import os
from datetime import datetime, timezone

load_dotenv()

# CONFIGURAÇÃO DE CHAVES E SERVIÇOS
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY") or os.getenv("KEY")
AWS_ACCESS_KEY_ID = os.getenv("aws_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("aws_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("aws_REGION", "us-east-1")

dynamodb = boto3.resource(
    'dynamodb',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION
)

# TABELAS
sentimentos_tabela = dynamodb.Table('CANDIFeelings')
sintomas_tabela = dynamodb.Table('CANDISymptoms')


def fetch_dynamodb_items_by_profile(tabela, profile_id, limit):
    try:
        response = tabela.scan(
            FilterExpression=Attr('profile_id').eq(profile_id)
        )

        items = response.get('Items', [])

        if items:
            try:
                items.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            except Exception:
                pass

        return items[:limit]

    except ClientError as e:
        print(f"Erro ao receber as informações da tabela {tabela.name}: {e}")
        return []


def convert_to_ai_string(sentimentos_data, sintomas_data):
    data_string = "Informações do Paciente:\n\n"

    # SENTIMENTOS
    if sentimentos_data:
        data_string += "=== SENTIMENTOS (últimas entradas) ===\n"
        for idx, sentimento in enumerate(sentimentos_data, 1):
            created_at = sentimento.get('created_at', 'N/A')
            happiness = sentimento.get('happiness', 'N/A')
            observation = sentimento.get('observation', '')

            happiness_desc = {
                1: "Muito Triste 😢",
                2: "Triste 😟",
                3: "Neutro 😐",
                4: "Feliz 😊",
                5: "Muito Feliz 😄"
            }.get(happiness, str(happiness))

            data_string += f"{idx}. [{created_at}]\n"
            data_string += f"   Nível de Felicidade: {happiness_desc}\n"
            if observation:
                data_string += f"   Observação: {observation}\n"
            data_string += "\n"
    else:
        data_string += "=== SENTIMENTOS ===\n(Nenhum registro encontrado)\n\n"

    # SINTOMAS
    if sintomas_data:
        data_string += "=== SINTOMAS (últimas entradas) ===\n"
        for idx, sintoma in enumerate(sintomas_data, 1):
            created_at = sintoma.get('created_at', 'N/A')
            description = sintoma.get('description', 'N/A')

            data_string += f"{idx}. [{created_at}]\n"
            data_string += f"   Descrição: {description}\n"
            data_string += "\n"
    else:
        data_string += "=== SINTOMAS ===\n(Nenhum registro encontrado)\n\n"

    return data_string


def generate_ai_insight(data: str):
    if not OPENROUTER_KEY:
        raise Exception("Chave OPENROUTER_KEY não configurada.")

    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json",
            },
            data=json.dumps({
                "model": "deepseek/deepseek-r1-0528-qwen3-8b:free",
                "messages": [{
                    "role": "user",
                    "content": f'Analise os seguintes dados de diário de saúde e forneça insights compassivos e úteis em português brasileiro:\n\n{data}'
                }],
            }),
            timeout=30
        )

        response.raise_for_status()
        data = response.json()
        return data['choices'][0]['message']['content']

    except requests.exceptions.RequestException as e:
        raise Exception(f"Erro ao chamar a API de IA: {str(e)}")


def lambda_handler(event, context):
    """
    AWS Lambda Entry Point
    Expects: event = { "uid": "<profile_id>" }
    """
    try:
        # Handle simple health check
        if event.get("path") == "/":
            try:
                sentimentos_tabela.table_status
                return {
                    "statusCode": 200,
                    "body": json.dumps({
                        "status": "healthy",
                        "dynamodb": "connected",
                        "message": "API totalmente no ar!!",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                }
            except Exception as e:
                return {
                    "statusCode": 500,
                    "body": json.dumps({
                        "status": "unhealthy",
                        "error": f"Erro de conexão DynamoDB/AWS: {str(e)}",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                }

        # MAIN AI LOGIC
        profile_id = event.get("uid") or event.get("pathParameters", {}).get("profile_id")
        if not profile_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing uid or profile_id"})
            }

        limit = 5
        sentimentos_data = fetch_dynamodb_items_by_profile(sentimentos_tabela, profile_id, limit)
        sintomas_data = fetch_dynamodb_items_by_profile(sintomas_tabela, profile_id, limit)

        if not sentimentos_data and not sintomas_data:
            return {
                "statusCode": 404,
                "body": json.dumps({
                    "error": f"Nenhum dado de sentimentos ou sintomas encontrado para o usuário {profile_id}."
                })
            }

        data_string = convert_to_ai_string(sentimentos_data, sintomas_data)
        ai_resposta = generate_ai_insight(data_string)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "profile_id": profile_id,
                "entries_analyzed": {
                    "sentimentos": len(sentimentos_data),
                    "sintomas": len(sintomas_data)
                },
                "ai_analysis": ai_resposta,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": f"Erro interno no processamento: {str(e)}"})
        }
