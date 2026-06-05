"""Schemas Pydantic de entrada e saída da API."""

from typing import List

from pydantic import BaseModel, Field


class AnalysisRequest(BaseModel):
    """Payload recebido pelo endpoint de análise."""

    text: str = Field(
        ...,
        description="Texto da recomendação de investimento a ser analisada.",
        examples=["Recomendo alocar 100% do patrimônio em criptomoedas."],
    )
    client_profile: str = Field(
        ...,
        description="Perfil de risco do cliente (ex.: conservador, moderado, agressivo).",
        examples=["conservador"],
    )


class SourceReference(BaseModel):
    """Referência a um trecho da base de conhecimento usado na análise."""

    source_document: str = Field(
        ...,
        description="Nome do arquivo de origem do trecho (ex.: resol_030_cvm.pdf).",
    )
    source_chunk_id: int = Field(
        ...,
        description="Índice do chunk dentro do documento de origem.",
    )
    relevance_score: float = Field(
        ...,
        description="Score de relevância pós re-ranking (maior = mais relevante).",
    )
    excerpt: str = Field(
        ...,
        description="Trecho do documento usado como contexto na análise.",
    )


class AnalysisResult(BaseModel):
    """Resultado estruturado da análise de conformidade."""

    is_compliant: bool = Field(
        ...,
        description="True se a recomendação está adequada ao perfil do cliente.",
    )
    reason: str = Field(
        ...,
        description="Justificativa da análise feita pelo modelo.",
    )
    mentioned_products: List[str] = Field(
        default_factory=list,
        description="Produtos financeiros citados na recomendação.",
    )
    sources: List[SourceReference] = Field(
        default_factory=list,
        description="Trechos da base de conhecimento que embasaram a análise.",
    )