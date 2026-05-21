"""Compliance Checker API - ponto de entrada FastAPI."""

import logging

from fastapi import FastAPI, HTTPException

from .api.schemas.analysis import AnalysisRequest, AnalysisResponse
from .core.exceptions import (
    APIConnectionError,
    InvalidConfigurationError,
    LLMResponseError,
)
from .services.compliance_service import analyze_text

logger = logging.getLogger(__name__)

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


@app.post("/analyze", response_model=AnalysisResponse, tags=["compliance"])
def analyze(request: AnalysisRequest) -> AnalysisResponse:
    """Recebe uma recomendação e retorna a análise de conformidade."""
    try:
        result = analyze_text(
            text=request.text_to_analyze,
            client_profile=request.client_profile,
        )
        if not result:
            raise APIConnectionError(
                "O serviço de análise não retornou resultado."
            )
        return AnalysisResponse(**result)

    except InvalidConfigurationError as e:
        logger.error("Configuração inválida: %s", e)
        raise HTTPException(
            status_code=503,
            detail=f"Serviço indisponível (configuração inválida): {e}",
        )
    except APIConnectionError as e:
        logger.error("Falha de conexão com o LLM: %s", e)
        raise HTTPException(status_code=503, detail=str(e))
    except LLMResponseError as e:
        logger.error("Resposta inválida do LLM: %s", e)
        raise HTTPException(
            status_code=502,
            detail=f"Resposta inválida do serviço de análise: {e}",
        )
    except HTTPException:
        # Re-lança HTTPException sem mascarar (evita virar 500).
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("Erro inesperado em /analyze")
        raise HTTPException(
            status_code=500,
            detail="Ocorreu um erro interno no servidor.",
        ) from e
