from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel

import requests
import json

# MODELO DOS DADOS; it WILL change
class DadosPaciente(BaseModel):
    info: str

app = FastAPI()

# FUNC PRINCIPAL PARA A IA
def infoToAI(data : str):
    response = requests.post(
    url="https://openrouter.ai/api/v1/chat/completions",
    headers={
        "Authorization": "Bearer <API-KEY>",
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
@app.get("/ai/{info}")
async def receivingInfo(info: str):
    # infoToAI(info)
    return "Ta indo!!"
