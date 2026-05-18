"""Lógica de negócio: análise de conformidade via LLM.

Usa o contrato público de `AzureModel` (arquivo imutável):
    - `AzureModel()`            -> instancia (config vinda do .env)
    - `llm_client.client`       -> cliente patcheado com `instructor`
                                   (suporta `response_model`)
    - `llm_client.deployment`   -> nome do deployment a usar como `model`
    - `llm_client.invoke(...)`  -> resposta crua (fallback)

A extração estruturada usa `instructor` via `llm_client.client`, que é
exatamente como o `AzureModel` foi projetado para ser usado.
"""

import json
import re

from ..api.schemas import AnalysisRequest, AnalysisResult
from ..core.llm_client import AzureModel


def _build_prompt(request: AnalysisRequest) -> str:
    return f"""
Você é um analista de compliance de serviços financeiros. Seja rigoroso.

Analise a seguinte recomendação de investimento:
\"\"\"{request.text}\"\"\"

O cliente possui perfil de risco: '{request.client_profile}'.

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


def analyze_recommendation(request: AnalysisRequest) -> AnalysisResult:
    """Usa o cliente LLM para analisar uma recomendação de investimento."""
    llm_client = AzureModel()
    prompt = _build_prompt(request)

    # Caminho principal: saída estruturada via `instructor`
    # (o cliente já vem patcheado em AzureModel.client).
    try:
        result: AnalysisResult = llm_client.client.chat.completions.create(
            model=llm_client.deployment,
            response_model=AnalysisResult,
            messages=[{"role": "user", "content": prompt}],
        )
        return result

    except Exception as e:  # noqa: BLE001
        # Fallback: chamada crua via invoke() + parse de JSON / heurística.
        try:
            json_prompt = (
                prompt
                + "\n\nResponda EXCLUSIVAMENTE com um JSON válido no formato:\n"
                + '{"is_compliant": true/false, "reason": "texto", '
                + '"mentioned_products": ["..."]}'
            )
            response = llm_client.invoke(prompt=json_prompt)
            raw_content = response.choices[0].message.content or ""

            try:
                data = _extract_json(raw_content)
                return AnalysisResult(
                    is_compliant=bool(data.get("is_compliant", False)),
                    reason=str(data.get("reason", raw_content)),
                    mentioned_products=list(data.get("mentioned_products", [])),
                )
            except (ValueError, json.JSONDecodeError):
                return AnalysisResult(
                    is_compliant="não" not in raw_content.lower(),
                    reason=raw_content,
                    mentioned_products=[],
                )

        except Exception as inner:  # noqa: BLE001
            return AnalysisResult(
                is_compliant=False,
                reason=f"Falha ao processar a análise: {inner} (erro inicial: {e})",
                mentioned_products=[],
            )