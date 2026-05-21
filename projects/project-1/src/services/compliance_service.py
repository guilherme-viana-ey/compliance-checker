"""Lógica de negócio: análise de conformidade via LLM."""

import json
import logging
import re
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ..core.exceptions import (
    APIConnectionError,
    InvalidConfigurationError,
    LLMResponseError,
)
from ..core.llm_client import AzureModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Modelo interno do service (usado APENAS pelo `instructor` para extração
# estruturada). Não vaza para fora: a função pública devolve `dict`.
# ---------------------------------------------------------------------------
class _LLMAnalysis(BaseModel):
    is_compliant: bool = Field(..., description="True se a recomendação é adequada ao perfil.")
    reason: str = Field(..., description="Justificativa objetiva da análise.")
    mentioned_products: List[str] = Field(
        default_factory=list, description="Produtos financeiros mencionados na recomendação."
    )


def _build_prompt(text: str, client_profile: str) -> str:
    return f"""
Você é um analista de compliance de serviços financeiros. Seja rigoroso.

Analise a seguinte recomendação de investimento:
\"\"\"{text}\"\"\"

O cliente possui perfil de risco: '{client_profile}'.

Tarefas:
1. Determine se a recomendação é adequada (compliant) para esse perfil.
2. Explique o motivo de forma objetiva.
3. Liste os produtos financeiros mencionados na recomendação.
""".strip()


def _extract_json(raw_content: str) -> dict:
    """Extrai o primeiro bloco JSON de uma string (tolerante a ruído)."""
    match = re.search(r"\{.*\}", raw_content, re.DOTALL)
    if not match:
        raise ValueError("Nenhum JSON encontrado na resposta do modelo.")
    return json.loads(match.group(0))


def _new_client() -> AzureModel:
    """Instancia o `AzureModel`, traduzindo erros de config."""
    try:
        return AzureModel()
    except ValueError as e:  # AzureModel lança ValueError se faltar env var
        raise InvalidConfigurationError(str(e)) from e


def analyze_text(text: str, client_profile: str) -> Dict[str, Any]:
    """Analisa uma recomendação de investimento.

    Args:
        text: Texto bruto da recomendação.
        client_profile: Perfil de risco do cliente (ex.: 'conservador').

    Returns:
        Dicionário com as chaves: `is_compliant`, `reason`,
        `mentioned_products`.

    Raises:
        InvalidConfigurationError: variáveis de ambiente ausentes.
        APIConnectionError: falha na comunicação com o LLM.
        LLMResponseError: o LLM respondeu, mas a resposta é inválida.
    """
    llm_client = _new_client()
    prompt = _build_prompt(text, client_profile)

    # ------------------------------------------------------------------
    # Caminho principal: saída estruturada via `instructor`.
    # ------------------------------------------------------------------
    try:
        result: _LLMAnalysis = llm_client.client.chat.completions.create(
            model=llm_client.deployment,
            response_model=_LLMAnalysis,
            messages=[{"role": "user", "content": prompt}],
        )
        return result.model_dump()
    except Exception as e:  # noqa: BLE001
        logger.warning("Extração estruturada via instructor falhou: %s", e)

    # ------------------------------------------------------------------
    # Fallback: chamada crua via invoke() + parse de JSON / heurística.
    # ------------------------------------------------------------------
    json_prompt = (
        prompt
        + "\n\nResponda EXCLUSIVAMENTE com um JSON válido no formato:\n"
        + '{"is_compliant": true/false, "reason": "texto", '
        + '"mentioned_products": ["..."]}'
    )

    try:
        response = llm_client.invoke(prompt=json_prompt)
    except Exception as e:  # noqa: BLE001
        raise APIConnectionError(
            f"Falha ao se comunicar com o serviço de LLM: {e}"
        ) from e

    raw_content = (response.choices[0].message.content or "").strip()
    if not raw_content:
        raise LLMResponseError("O LLM retornou resposta vazia.")

    try:
        data = _extract_json(raw_content)
        return {
            "is_compliant": bool(data.get("is_compliant", False)),
            "reason": str(data.get("reason", raw_content)),
            "mentioned_products": list(data.get("mentioned_products", [])),
        }
    except (ValueError, json.JSONDecodeError) as e:
        raise LLMResponseError(
            f"Não foi possível interpretar a resposta do LLM: {e}"
        ) from e
