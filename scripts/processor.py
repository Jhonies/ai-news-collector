"""
scripts/processor.py — Gerador de resumos via Ollama (local).

Responsavel por chamar o modelo LLM local para produzir resumo e headline
a partir do conteudo extraido de cada noticia.
"""

from __future__ import annotations

import json
import logging
import os
import re

import requests
from typing import TypedDict

# ──────────────────────────────────────────
#  CONFIGURACAO
# ──────────────────────────────────────────

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL   = os.getenv("OLLAMA_MODEL", "phi3:latest")
REQUEST_TIMEOUT = 120

logger = logging.getLogger(__name__)


class ResumoResult(TypedDict):
    summary: str
    headline: str


# ──────────────────────────────────────────
#  VERIFICACAO DO OLLAMA
# ──────────────────────────────────────────

def ollama_disponivel(base_url: str = OLLAMA_BASE_URL) -> bool:
    """Verifica se o servidor Ollama esta acessivel."""
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=5)
        return resp.status_code == 200
    except requests.ConnectionError:
        return False


def listar_modelos(base_url: str = OLLAMA_BASE_URL) -> list[str]:
    """Retorna lista de modelos disponiveis no Ollama local."""
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return [m["name"] for m in data.get("models", [])]
    except requests.RequestException as exc:
        logger.warning("[WARN] Falha ao listar modelos: %s", exc)
        return []


# ──────────────────────────────────────────
#  CHAMADA AO OLLAMA
# ──────────────────────────────────────────

def _chamar_ollama(
    prompt: str,
    model: str = DEFAULT_MODEL,
    base_url: str = OLLAMA_BASE_URL,
) -> str:
    """Envia prompt ao Ollama via /api/generate e retorna a resposta textual."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": 500,
        },
    }

    resp = requests.post(
        f"{base_url}/api/generate",
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()

    return resp.json().get("response", "").strip()


# ──────────────────────────────────────────
#  GERACAO DE RESUMO
# ──────────────────────────────────────────

def gerar_resumo(
    titulo: str,
    conteudo: str,
    model: str = DEFAULT_MODEL,
    base_url: str = OLLAMA_BASE_URL,
    lingua: str = "portugues brasileiro",
) -> ResumoResult:
    """
    Gera resumo e headline para uma noticia usando o Ollama local.

    Retorna dict com 'summary' e 'headline'. Em caso de falha,
    retorna valores fallback sem levantar excecao.
    """
    conteudo_truncado = conteudo[:3500] if conteudo else ""
    if not conteudo_truncado:
        return {"summary": "Conteudo nao disponivel.", "headline": titulo}

    prompt = (
        f"Voce e um especialista em IA. Produza EXATAMENTE o JSON abaixo.\n"
        f"REGRAS: Responda APENAS com JSON. Sem markdown.\n"
        f'FORMATO: {{"summary": "resumo de 3-5 linhas para redes sociais em {lingua}", '
        f'"headline": "frase curta e chamativa para Instagram"}}\n'
        f"NOTICIA: {titulo}\n"
        f"CONTEUDO: {conteudo_truncado}\n"
        f"JSON:"
    )

    try:
        resposta_raw = _chamar_ollama(prompt, model=model, base_url=base_url)

        match = re.search(r"\{.*\}", resposta_raw, re.DOTALL)
        if match:
            dados = json.loads(match.group(0))
            return {
                "summary": dados.get("summary", ""),
                "headline": dados.get("headline", titulo),
            }

        return {"summary": resposta_raw[:800], "headline": titulo}

    except requests.Timeout:
        logger.warning("[WARN] Timeout ao chamar Ollama para '%s'", titulo[:60])
        return {"summary": "Timeout ao gerar resumo.", "headline": titulo}
    except requests.RequestException as exc:
        logger.error("[ERROR] Falha de rede com Ollama: %s", exc)
        return {"summary": f"Erro de rede: {exc}", "headline": titulo}
    except json.JSONDecodeError as exc:
        logger.warning("[WARN] Resposta do Ollama nao e JSON valido: %s", exc)
        return {"summary": resposta_raw[:800], "headline": titulo}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if not ollama_disponivel():
        logger.error("[ERROR] Ollama offline.")
    else:
        logger.info("[INFO] Ollama online! Usando: %s", DEFAULT_MODEL)
        resultado = gerar_resumo("Teste", "O GPT-5 sera incrivel e multimodal.")
        logger.info("[INFO] Resumo: %s", resultado["summary"])
