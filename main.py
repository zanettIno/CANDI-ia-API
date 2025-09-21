from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

import requests
import json
import os

# MODELO DOS DADOS; it WILL change
class DadosPaciente(BaseModel):
    info: str

app = FastAPI()
load_dotenv()
API_KEY = os.getenv("KEY")

# FUNC PRINCIPAL PARA A IA
def infoToAI(data : str):
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
                "content": f'Tell me, in brazilian portuguese, what do you think about: {data}'
        }],
    })
    )

    data = response.json()
    return data['choices'][0]['message']['content']

@app.get("/")
async def main():
    return "API totalmente no ar!!"

# RECEBIMENTO DOS DADOS
# @app.get("/ai/{info}")
# async def receivingInfo(info: str):
    # print(info)
    # retorno = infoToAI(info)
    # return retorno

# RECEBIMENTO DOS DADOS (EMULACAO)
@app.get("/ai/")
async def receivingInfo(info: str):
    retorno = infoToAI(cancer)
    return retorno
