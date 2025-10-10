from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

import requests
import json
import os
from datetime import datetime

# MODELO DOS DADOS
class DadosPaciente(BaseModel):
    userId: str

app = FastAPI()
load_dotenv()

# CHAVES API
API_KEY = os.getenv("KEY")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

dynamodb = boto3.resource(
    'dynamodb',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION
)

# TABELAS
sentimentosTabela = dynamodb.Table('CANDIFeelings')
sintomasTabela = dynamodb.Table('CANDISymptoms')

def fetchSentimentosSintomas(tabela, profileId, limit=5):
    try:
        response = tabela.query(
            KeyConditionExpression=Key('profile_id').eq(profileId),
            ScanIndexForward=False,  
            Limit=limit
        )
        return response.get('Items', [])
    except ClientError as e:
        print(f"Erro recebendo as informacoes: {e}")
        return []

def converterString(sentimentosData, sintomasData):
    dataString = "Informações do Paciente:\n\n"
    
    dataString += "=== SENTIMENTOS (últimas 5 entradas) ===\n"
    for idx, sentimento in enumerate(sentimentosData, 1):
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
        
        dataString += f"{idx}. [{created_at}]\n"
        dataString += f"   Nível de Felicidade: {happiness_desc}\n"
        if observation:
            dataString += f"   Observação: {observation}\n"
        dataString += "\n"
    
    dataString += "=== SINTOMAS (últimas 5 entradas) ===\n"
    for idx, sintoma in enumerate(sintomasData, 1):
        created_at = sintoma.get('created_at', 'N/A')
        description = sintoma.get('description', 'N/A')
        
        dataString += f"{idx}. [{created_at}]\n"
        dataString += f"   Descrição: {description}\n"
        dataString += "\n"
    
    return dataString

# FUNC PRINCIPAL PARA A IA
def infoToAI(data: str):
    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {API_KEY}",
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
        raise HTTPException(status_code=500, detail=f"Erro ao chamar a API: {str(e)}")

@app.get("/")
async def main():
    try:
        sentimentosTabela.table_status
        return {
            "status": "healthy",
            "dynamodb": "connected",
            "message": "API totalmente no ar!!",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

@app.get("/ai/{profile_id}")
async def AI(profile_id: str):
    try:
        sentimentosData = fetchSentimentosSintomas(sentimentosTabela, profile_id, limit=5)
        sintomasData = fetchSentimentosSintomas(sintomasTabela, profile_id, limit=5)
        
        if not sentimentosData and not sintomasData:
            raise HTTPException(
                status_code=404, 
                detail="Nenhum dado encontrado para este usuário"
            )
        
        dataString = converterString(sentimentosData, sintomasData)
        AIResposta = infoToAI(dataString)
        
        return {
            "profile_id": profile_id,
            "entries_analyzed": {
                "sentimentos": len(sentimentosData),
                "sintomas": len(sintomasData)
            },
            "ai_analysis": AIResposta
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(e)}")
