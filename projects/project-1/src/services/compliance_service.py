"""Lógica de negócio: análise de conformidade via RAG + LLM.

Fluxo orquestrado:
1. Recebe a requisição (texto + perfil do cliente)
2. Chama o serviço de recuperação (retrieval.py) para buscar os chunks relevantes
3. Aplica re-ranking automático (feito dentro do retrieve())
4. Constrói um prompt enriquecido com o contexto recuperado (Strict Grounding)
5. Chama o LLM com o prompt enriquecido
6. Retorna o resultado incluindo as fontes usadas na análise

Usa o contrato público de `AzureModel` (arquivo imutável):
    - `AzureModel()`            -> instancia (config vinda do .env)
    - `llm_client.client`       -> cliente patcheado com `instructor`
    - `llm_client.deployment`   -> nome do deployment
    - `llm_client.invoke(...)`  -> resposta crua (fallback)
"""

import json
import re

from ..api.schemas import AnalysisRequest, AnalysisResult, SourceReference
from ..core.llm_client import AzureModel
from ..rag.retrieval import format_context, retrieve


# =========================
# ✅ PROMPT ENRIQUECIDO (STRICT GROUNDING)
# =========================
def _build_rag_prompt(request: AnalysisRequest, context: str) -> str:
    return f"""
Você é um analista sênior de compliance de serviços financeiros. Sua análise deve ser
rigorosa e embasada EXCLUSIVAMENTE nos trechos de documentos oficiais fornecidos abaixo.
Não use conhecimento externo. Se o contexto não for suficiente para uma conclusão
definitiva, indique isso explicitamente no campo "reason".

=============================================
CONTEXTO REGULATÓRIO RECUPERADO:
=============================================
{context}
=============================================

Analise a seguinte recomendação de investimento:
\"\"\"{request.text}\"\"\"

O cliente possui perfil de risco: '{request.client_profile}'.

Com base APENAS nos trechos acima, execute as tarefas:
1. Determine se a recomendação é adequada (compliant) para o perfil informado.
2. Justifique citando explicitamente as regras ou cláusulas dos documentos fornecidos.
3. Liste os produtos financeiros mencionados na recomendação.
""".strip()


# =========================
# ✅ PARSE DE RESPOSTA CRUA (FALLBACK)
# =========================
def _extract_json(raw_content: str) -> dict:
    """Extrai o primeiro bloco JSON de uma string (tolerante a ruído)."""
    match = re.search(r"\{.*\}", raw_content, re.DOTALL)
    if not match:
        raise ValueError("Nenhum JSON encontrado na resposta do modelo.")
    return json.loads(match.group(0))


# =========================
# ✅ ORQUESTRADOR PRINCIPAL
# =========================
def analyze_recommendation(request: AnalysisRequest) -> AnalysisResult:
    """
    Orquestra o fluxo RAG completo:
    retrieval → re-ranking → prompt enriquecido → LLM → resposta com fontes.
    """
    # ── 1. Recuperação + Re-ranking ──────────────────────────────────────────
    chunks = retrieve(query=request.text)
    context = format_context(chunks)

    # ── 2. Monta as referências de fonte para incluir na resposta ────────────
    sources = [
        SourceReference(
            source_document=chunk.source_document,
            source_chunk_id=chunk.chunk_id,
            relevance_score=round(chunk.rerank_score, 4),
            excerpt=chunk.content[:300].strip(),  # preview do trecho
        )
        for chunk in chunks
    ]

    # ── 3. Prompt enriquecido com contexto ───────────────────────────────────
    prompt = _build_rag_prompt(request, context)
    llm_client = AzureModel()

    # ── 4. Caminho principal: saída estruturada via instructor ───────────────
    try:
        # O instructor não preenche `sources` automaticamente (vem do retrieval),
        # por isso usamos um modelo intermediário sem o campo e montamos o resultado.
        from pydantic import BaseModel
        from typing import List

        class _LLMResult(BaseModel):
            is_compliant: bool
            reason: str
            mentioned_products: List[str] = []

        llm_result: _LLMResult = llm_client.client.chat.completions.create(
            model=llm_client.deployment,
            response_model=_LLMResult,
            messages=[{"role": "user", "content": prompt}],
        )

        return AnalysisResult(
            is_compliant=llm_result.is_compliant,
            reason=llm_result.reason,
            mentioned_products=llm_result.mentioned_products,
            sources=sources,
        )

    except Exception as e:  # noqa: BLE001
        # ── 5. Fallback: chamada crua + parse de JSON ────────────────────────
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
                    sources=sources,
                )
            except (ValueError, json.JSONDecodeError):
                return AnalysisResult(
                    is_compliant="não" not in raw_content.lower(),
                    reason=raw_content,
                    mentioned_products=[],
                    sources=sources,
                )

        except Exception as inner:  # noqa: BLE001
            return AnalysisResult(
                is_compliant=False,
                reason=f"Falha ao processar a análise: {inner} (erro inicial: {e})",
                mentioned_products=[],
                sources=sources,
            )