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