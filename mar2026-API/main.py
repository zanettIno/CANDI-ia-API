import datetime
import hashlib
import logging
import re
from decimal import Decimal
import secrets

from google import genai
from dotenv import load_dotenv
import boto3
from botocore.exceptions import ClientError
import json
import os

load_dotenv()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

client = genai.Client(api_key=os.getenv("CHAVE_API"))

AWS_ACCESS_KEY_ID = os.getenv("aws_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("aws_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("aws_REGION", "us-east-1")

dynamodb = boto3.resource(
    'dynamodb',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION,
    config=boto3.session.Config(
        connect_timeout=5,
        read_timeout=5,
        retries={'max_attempts': 2}
    )
)

sentimentos_tabela = dynamodb.Table('CANDIFeelings')
sintomas_tabela = dynamodb.Table('CANDISymptoms')

# ─────────────────────────────────────────────
# >> Anonimização do profile_id
# O identificador real NUNCA é enviado ao Gemini.
# Um hash SHA-256 truncado (16 chars) substitui o ID
# antes de qualquer montagem de payload para a IA.
# ─────────────────────────────────────────────

def anonymize_profile_id(profile_id: str) -> str:
    salt = os.getenv("ANONYMIZATION_SALT") 
    if not salt:
        raise ValueError("ANONYMIZATION_SALT não definido!")
    return hashlib.sha256(f"{salt}:{profile_id}".encode()).hexdigest()[:16]

# ─────────────────────────────────────────────
# >> Sanitização de PII em texto livre
# Regex cobre CPF, telefone, e-mail e nomes compostos (mantidos)
# Nova passagem por tokenização captura nomes próprios SIMPLES
# Blocklist de palavras seguras evita falsos positivos em meses,
# dias da semana e cidades comuns
#
# Limitação documentada: heurística baseada em regex e tokenização.
# ─────────────────────────────────────────────

# Palavras capitalizadas que NÃO devem ser tratadas como nomes próprios
SAFE_CAPITALIZED_WORDS = {
    # Dias e Meses
    'Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo',
    'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
    'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
    
    # Localidades e Instituições
    'São', 'Rio', 'Belo', 'Porto', 'Nova', 'Santa', 'Hospital', 'Clínica', 
    'Unidade', 'Centro', 'Instituto', 'Brasil', 'Estado', 'Cidade', 'Rua', 
    'Avenida', 'Bairro', 'Posto', 'Upa', 'Ambulatório',

    # Anatomia (Os maiores culpados de falsos positivos)
    'Braço', 'Perna', 'Cabeça', 'Cérebro', 'Coração', 'Pulmão', 'Fígado', 
    'Rins', 'Estômago', 'Barriga', 'Peito', 'Costas', 'Ombro', 'Pescoço', 
    'Rosto', 'Mão', 'Pé', 'Dedo', 'Joelho', 'Cotovelo', 'Garganta', 'Ouvido', 
    'Olho', 'Nariz', 'Boca', 'Língua', 'Dente', 'Coluna', 'Ventre',

    # Termos Médicos e Clínicos
    'Oncologia', 'Quimio', 'Radio', 'Radioterapia', 'Exame', 'Sangue', 
    'Urina', 'Consulta', 'Receita', 'Atestado', 'Cirurgia', 'Tratamento',
    'Doutor', 'Doutora', 'Médico', 'Médica', 'Enfermeiro', 'Enfermeira',
    'Comprimido', 'Cápsula', 'Ampola', 'Medicamento', 'Remédio', 'Dose',

    # Substantivos Comuns de Diário
    'Deus', 'Família', 'Trabalho', 'Escola', 'Faculdade', 'Casa', 'Igreja',
    'Manhã', 'Tarde', 'Noite', 'Ontem', 'Hoje', 'Amanhã', 'Semana'}

PII_PATTERNS = [
    # CPF
    (r'\d{3}[\.\s]?\d{3}[\.\s]?\d{3}[-\.\s]?\d{2}', '[CPF_REMOVIDO]'),

    # Telefone
    (r'(\(?\d{2}\)?\s?)?(\d{4,5}[-\s]?\d{4})', '[TELEFONE_REMOVIDO]'),

    # E-mail
    (r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[EMAIL_REMOVIDO]'),

    # Nomes próprios compostos (duas palavras capitalizadas seguidas)
    (r'\b[A-Z][a-záéíóúãõâêî]{2,}\s[A-Z][a-záéíóúãõâêî]{2,}\b', '[NOME_REMOVIDO]')]

def sanitize_free_text(text: str) -> str:
    """
    Remove padrões de PII identificáveis de texto livre antes do envio à IA.

    Etapa 1 — Regex: CPF, telefone, e-mail, nomes compostos.
    Etapa 2 — Tokenização: nomes próprios simples mid-sentence
              que escapam do regex (ex: "Maicon", "Carla").
    """

    if not text:
        return text

    # Etapa 1 — regex patterns
    sanitized = text
    for pattern, replacement in PII_PATTERNS:
        sanitized = re.sub(pattern, replacement, sanitized)

    # Etapa 2 — tokenização para nomes simples mid-sentence (1.1)
    tokens = sanitized.split()
    result = []
    for i, token in enumerate(tokens):
        # Remove pontuação adjacente para comparar o token limpo
        clean = re.sub(r'[^\w]', '', token)

        is_long_enough   = len(clean) >= 3
        is_capitalized   = bool(re.match(r'^[A-Z][a-záéíóúãõâêî]+$', clean))
        is_safe_word     = clean in SAFE_CAPITALIZED_WORDS
        is_sentence_start = (
            i == 0 or
            (i > 0 and re.search(r'[.!?]$', tokens[i - 1]) is not None)
        )

        if is_long_enough and is_capitalized and not is_safe_word and not is_sentence_start:
            result.append(token.replace(clean, '[NOME_REMOVIDO]'))
        else:
            result.append(token)

    return ' '.join(result)

# ─────────────────────────────────────────────
# >> Detecção de risco clínico
# Intercepta terminologia de alto risco antes do envio à IA,
# evitando que o modelo faça triagem ou inferência diagnóstica
# não supervisionada sobre sintomas graves.
#
# Substitui os termos por um placeholder neutro e retorna um
# flag booleano que será usado para ajustar o prompt da IA.
# ─────────────────────────────────────────────

CLINICAL_RISK_PATTERNS = [
    r'\bteto\s+preto\b',
    r'\bdesmai\w*\b',
    r'\bsíncope\b',
    r'\bconvuls\w*\b',
    r'\bme\s+machuqu\w*\b',
    r'\bme\s+ferir?\b',
    r'\bautolesã\w*\b',
    r'\bsuicíd\w*\b',
    r'\bme\s+matar?\b',
    r'\bme\s+mato\b',
    r'\bquer\w*\s+morrer?\b',

    r'\btontura\w*\b',
    r'\bvisão\s+turva\b',
    r'\bvisão\s+embaraçad\w*\b',
    r'\bfalta\s+de\s+ar\b',
    r'\bfalta\s+d[\'\"]ar\b',
    r'\bdificuldade\s+para\s+respirar\b',
    r'\bpalpita\w*\b',
    r'\btaquicard\w*\b',
    r'\bdormên\w*\b',
    r'\bformigament\w*\b',
    r'\bpressão\s+alta\b',
    r'\bhipertens\w*\b',
    r'\binjúria\w*\b',
    r'\bfratura\w*\b']

def flag_clinical_risk(text: str) -> tuple[str, bool]:
    """
    Substitui terminologia de risco clínico no texto antes do envio à IA.

    Retorna:
        (texto_sanitizado, houve_risco_clinico: bool)

    O flag booleano é usado em convert_to_ai_format para adicionar
    um aviso no payload que instrui a IA a não fazer diagnósticos.
    """
    if not text:
        return text, False

    houve_risco = False
    sanitized = text
    for pattern in CLINICAL_RISK_PATTERNS:
        if re.search(pattern, sanitized, re.IGNORECASE):
            houve_risco = True
            sanitized = re.sub(
                pattern,
                '[SINTOMA_CLINICO_REGISTRADO]',
                sanitized,
                flags=re.IGNORECASE
            )
    return sanitized, houve_risco

# ─────────────────────────────────────────────
# >> Generalização de timestamps
# Timestamps exatos aumentam reidentificabilidade.
# Para análise de padrões emocionais, dia da semana
# e período do dia são suficientes e mais seguros.
# ─────────────────────────────────────────────

def generalize_timestamp(iso_timestamp: str) -> dict:
    try:
        dt = datetime.datetime.fromisoformat(iso_timestamp)
        dias = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo']

        hora = dt.hour
        if hora < 12:
            periodo = "manhã"
        elif hora < 18:
            periodo = "tarde"
        else:
            periodo = "noite"

        return {
            "dia_semana": dias[dt.weekday()],
            "periodo_dia": periodo,
            "semana_do_mes": (dt.day - 1) // 7 + 1
        }
    except (ValueError, TypeError):
        return {"periodo": "desconhecido"}

# ─────────────────────────────────────────────
# Utilitário de serialização
# ─────────────────────────────────────────────

def convert_decimal_to_native(obj):
    """Convert Decimal objects to int or float for JSON serialization."""
    if isinstance(obj, Decimal):
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    elif isinstance(obj, dict):
        return {k: convert_decimal_to_native(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimal_to_native(item) for item in obj]
    return obj


def fetch_dynamodb_items_by_profile(tabela, profile_id, limit):
    try:
        response = tabela.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr('profile_id').eq(profile_id)
        )

        items = response.get('Items', [])

        if items:
            try:
                items.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            except Exception:
                pass

        return items[:limit]

    except ClientError as e:
        logger.error(f"Erro ao receber as informações da tabela {tabela.name}: {e}", exc_info=True)
        return []

# ─────────────────────────────────────────────
# >> Sanitização do output da IA
# Segunda passagem de sanitização aplicada ao JSON retornado
# pelo Gemini antes de chegar ao cliente. Garante que nomes
# ou termos que escaparam do input não apareçam na resposta.
# ─────────────────────────────────────────────

def sanitize_ai_output(obj):
    """
    Aplica sanitize_free_text recursivamente em todo o JSON de resposta da IA.
    Cobre strings em qualquer nível de aninhamento (dict, list, string).
    """
    if isinstance(obj, dict):
        return {k: sanitize_ai_output(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_ai_output(item) for item in obj]
    elif isinstance(obj, str):
        return sanitize_free_text(obj)
    return obj

def convert_to_ai_format(sentimentos_data, sintomas_data, profile_id: str):
    """
    Converte dados do DynamoDB para formato otimizado para a IA, aplicando:
    - Anonimização do identificador 
    - Sanitização de PII e nomes simples no texto livre
    - Detecção e sinalização de risco clínico 
    - Generalização de timestamps 
    - Validação leve de sintomas com truncamento
    - Resumo estatístico como dado primário; texto livre como complemento
    """
    happiness_map = {
        1: {"label": "Muito Triste", "emoji": "😢", "severity": "high",   "sentiment": "negativo"},
        2: {"label": "Triste",       "emoji": "😟", "severity": "medium", "sentiment": "negativo"},
        3: {"label": "Neutro",       "emoji": "😐", "severity": "low",    "sentiment": "neutro"},
        4: {"label": "Feliz",        "emoji": "😊", "severity": "low",    "sentiment": "positivo"},
        5: {"label": "Muito Feliz",  "emoji": "😄", "severity": "none",   "sentiment": "positivo"},
    }

    anonymous_id = anonymize_profile_id(profile_id)

    happiness_values = [s.get('happiness', 0) for s in sentimentos_data if s.get('happiness')]
    media_bem_estar  = round(sum(happiness_values) / len(happiness_values), 1) if happiness_values else 0
    distribuicao     = {}
    for v in happiness_values:
        distribuicao[happiness_map.get(v, {}).get('label', 'Desconhecido')] = \
            distribuicao.get(happiness_map.get(v, {}).get('label', 'Desconhecido'), 0) + 1

    if media_bem_estar >= 4:
        tendencia_geral = "positiva"
    elif media_bem_estar <= 2:
        tendencia_geral = "negativa"
    else:
        tendencia_geral = "neutra"

    periodos = [
        generalize_timestamp(s.get('created_at', '')).get('periodo_dia', '')
        for s in sentimentos_data
    ]

    resumo_estatistico = {
        "media_bem_estar_escala_1_a_5": media_bem_estar,
        "tendencia_geral": tendencia_geral,
        "distribuicao_sentimentos": distribuicao,
        "periodos_de_registro": list(set(p for p in periodos if p)),
        "total_registros_analisados": len(sentimentos_data),
    }

    houve_risco_clinico = False
    sentimentos_formatted = []

    for s in sentimentos_data:
        level = happiness_map.get(
            s.get('happiness'),
            {"label": "Desconhecido", "emoji": "❓", "severity": "unknown", "sentiment": "unknown"}
        )

        observacao_sanitizada = sanitize_free_text(s.get('observation', ''))

        observacao_sanitizada, risco = flag_clinical_risk(observacao_sanitizada)
        if risco:
            houve_risco_clinico = True

        sentimentos_formatted.append({
            "periodo_registro":        generalize_timestamp(s.get('created_at', '')),
            "nivel_felicidade":        level["label"],
            "gravidade_emocional":     level["severity"],
            "classificacao_sentimento": level["sentiment"],
          
            "observacao":              observacao_sanitizada,
        })
    
    sintomas_formatted = []

    for s in sintomas_data:

        descricao_bruta = (s.get('description', '') or '')[:120]

        descricao_sanitizada = sanitize_free_text(descricao_bruta)

        descricao_sanitizada, risco = flag_clinical_risk(descricao_sanitizada)
        if risco:
            houve_risco_clinico = True

        sintomas_formatted.append({
            "periodo_registro": generalize_timestamp(s.get('created_at', '')),
            "descricao":        descricao_sanitizada,
        })

    return convert_decimal_to_native({
        "paciente": {
           
            "referencia_anonima": anonymous_id,
            "total_registros_sentimentos": len(sentimentos_data),
            "total_registros_sintomas":    len(sintomas_data),
            "periodo_analisado":           "últimos registros",
           
            "aviso_sistema": (
                "ATENÇÃO: Este paciente registrou termos que indicam possível "
                "sintoma físico sério. NÃO faça diagnósticos nem inferências clínicas. "
                "Limite-se a sugerir consulta médica de forma gentil e genérica."
                if houve_risco_clinico else ""
            ),
        },
      
        "resumo_estatistico": resumo_estatistico,
      
        "sentimentos": sentimentos_formatted,
        "sintomas":    sintomas_formatted,
    })

def generate_ai_insight(data_dict: dict):
    """Gera insights estruturados usando Gemini Flash 2.5 com prompt otimizado em português."""

    # ─────────────────────────────────────────────────────────────────────
    system_prompt = """Você é o CANDI, um assistente de saúde mental especializado em analisar diários de bem-estar emocional. Você combina empatia humana com análise profissional para oferecer suporte genuíno aos pacientes.

CONTEXTO DA ANÁLISE:
- Os dados representam registros de um diário de saúde emocional
- Cada entrada inclui sentimentos (escala 1-5) e sintomas relatados
- O usuário é um paciente buscando entender seu próprio bem-estar
- A resposta será consumida por um aplicativo móvel

SUA MISSÃO:
Analise os dados fornecidos e gere uma resposta estruturada em JSON que seja útil, acolhedora e acionável para o paciente. Priorize o resumo estatístico (campo "resumo_estatistico") como base da sua análise — os registros individuais são apenas contexto complementar.

DIRETRIZES DE COMPORTAMENTO:
1. Seja empático mas profissional - use tom acolhedor, não clínico
2. Identifique padrões sutis entre sentimentos e sintomas
3. Sugira ações específicas que o paciente pode fazer HOJE
4. Reconheça progressos, mesmo pequenos
5. Use linguagem inclusiva e não julgadora
6. Se detectar sinais de preocupação, aborde com gentileza

REGRAS DE PRIVACIDADE — OBRIGATÓRIAS:
- NUNCA reproduza nomes próprios de pessoas presentes nas observações.
  Se encontrar um nome, substitua por expressões como "alguém próximo" ou "uma pessoa importante".
- NUNCA transcreva trechos literais das observações do paciente.
  Faça sempre paráfrases genéricas: em vez de "Aniversário de Fulano", escreva
  "um evento social comemorativo com pessoas próximas".
- Se encontrar o marcador [SINTOMA_CLINICO_REGISTRADO] nos dados, NÃO faça
  inferência diagnóstica. Limite-se a sugerir consulta médica de forma gentil e genérica,
  sem especular sobre a causa ou gravidade do sintoma.
- Se o campo "aviso_sistema" estiver preenchido, siga estritamente sua instrução.
- Sua resposta será lida pelo próprio paciente — jamais mencione detalhes que
  possam identificar terceiros ou expor informações sensíveis de forma literal.

FORMATO OBRIGATÓRIO DE RESPOSTA (JSON):
{
    "resumo_empatico": "string - Uma frase acolhedora que reconheça o estado emocional atual do paciente de forma pessoal",
    "analise_sentimentos": {
        "tendencia_geral": "string - Tendência emocional (positiva/negativa/estável/flutuante)",
        "analise_detalhada": "string - Análise profunda dos sentimentos registrados, padrões observados",
        "emocoes_predominantes": ["lista de emoções principais identificadas"],
        "observacoes_relevantes": "string - Pontos importantes das observações, sem reproduzir literalmente nem mencionar nomes"
    },
    "analise_sintomas": {
        "frequencia_e_padrao": "string - Como os sintomas estão aparecendo",
        "possiveis_gatilhos": "string - Correlações observadas entre sentimentos negativos e sintomas",
        "impacto_na_rotina": "string - Estimativa do impacto baseado nos dados"
    },
    "recomendacoes": [
        "ação prática e específica 1",
        "ação prática e específica 2",
        "ação prática e específica 3"
    ],
    "alerta_saude_mental": {
        "nivel": "string - 'nenhum', 'baixo', 'moderado', 'alto' (baseado em padrões preocupantes)",
        "mensagem": "string - Alerta gentil se necessário, ou campo vazio se não houver preocupação",
        "sugestao_profissional": "boolean - true se recomendar buscar ajuda profissional"
    },
    "encorajamento": "string - Uma frase motivacional personalizada baseada nos dados",
    "proximos_passos": "string - Sugestão específica do que o paciente pode registrar nos próximos dias para melhorar a análise"
}

REGRAS CRÍTICAS:
- Retorne APENAS o JSON válido, sem markdown, sem texto antes ou depois
- Não use blocos de código markdown (```json), retorne JSON puro
- Se os dados forem insuficientes, indique isso nas análises de forma construtiva
- Mantenha o tom sempre acolhedor, nunca alarmista
- As recomendações devem ser ações concretas que podem ser feitas imediatamente"""

    data_json = json.dumps(data_dict, ensure_ascii=False, indent=2)

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"{system_prompt}\n\nDADOS DO PACIENTE (JSON):\n{data_json}"
    )

    return response.text


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
                        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
                    })
                }
            except Exception as e:
                logger.error(f"Health check falhou: {e}", exc_info=True)
                return {
                    "statusCode": 500,
                    "body": json.dumps({
                        "status": "unhealthy",
                        "error": "Erro de conexão com o serviço de armazenamento.",
                        "codigo": "STORAGE_UNREACHABLE",
                        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
                    })
                }

        # MAIN AI LOGIC
        profile_id = event.get("uid") or event.get("pathParameters", {}).get("profile_id")
        if not profile_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing uid or profile_id"})
            }

        limit = 6
        sentimentos_data = fetch_dynamodb_items_by_profile(sentimentos_tabela, profile_id, limit)
        sintomas_data    = fetch_dynamodb_items_by_profile(sintomas_tabela,    profile_id, limit)

        if not sentimentos_data and not sintomas_data:
            return {
                "statusCode": 404,
                "body": json.dumps({
                    "error": "Nenhum dado encontrado para o usuário informado."
                })
            }

        # 1.1 + 1.2 + 2.1 + 2.2 + 3.1 aplicados dentro de convert_to_ai_format
        data_structured = convert_to_ai_format(sentimentos_data, sintomas_data, profile_id)
        ai_resposta     = generate_ai_insight(data_structured)

        try:
            ai_json = json.loads(ai_resposta)
            # 1.3 — segunda passagem de sanitização no output da IA
            ai_json = sanitize_ai_output(ai_json)
        except json.JSONDecodeError:
            ai_json = {
                "resposta_bruta": sanitize_free_text(ai_resposta),
                "erro_parse": True
            }

        return {
            "statusCode": 200,
            "body": json.dumps({
                "entries_analyzed": {
                    "sentimentos": len(sentimentos_data),
                    "sintomas":    len(sintomas_data)
                },
                "ai_analysis": ai_json,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }, ensure_ascii=False)
        }

    except ClientError as e:
        logger.error(f"AWS ClientError: {e}", exc_info=True)
        return {
            "statusCode": 503,
            "body": json.dumps({
                "error": "Serviço temporariamente indisponível.",
                "codigo": "STORAGE_ERROR"
            })
        }

    except Exception as e:
        logger.error(f"Erro inesperado no lambda_handler: {e}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": "Erro interno. Tente novamente.",
                "codigo": "INTERNAL_ERROR"
            })
        }