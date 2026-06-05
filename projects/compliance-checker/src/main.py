"""Compliance Checker API - ponto de entrada FastAPI."""

from fastapi import FastAPI

from .api.schemas import AnalysisRequest, AnalysisResult
from .services.compliance_service import analyze_recommendation

app = FastAPI(
    title="Compliance Checker API",
    description=(
        "Serviço especialista que simula um analista de compliance, "
        "analisando recomendações de investimento com auxílio de um LLM."
    ),
    version="1.0.0",
)


@app.get("/", tags=["health"])
def health_check():
    """Verificação simples de saúde da API."""
    return {"status": "ok", "service": "Compliance Checker API"}


@app.post("/analyze", response_model=AnalysisResult, tags=["compliance"])
def analyze(request: AnalysisRequest) -> AnalysisResult:
    """Recebe uma recomendação e retorna a análise de conformidade."""
    return analyze_recommendation(request)