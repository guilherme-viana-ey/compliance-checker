"""Testes de integração da API.

Usamos o `TestClient` do FastAPI para fazer chamadas HTTP reais ao
endpoint `/analyze`, mas mockamos a função `analyze_text` (do service)
para não depender do LLM. O objetivo é validar:

- Status code correto em cada cenário (200, 422, 502, 503, 500).
- Validação Pydantic da entrada (`min_length=10`).
- Schema da resposta (`AnalysisResponse`).
- Tradução de exceções customizadas em `HTTPException`.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.core.exceptions import (
    APIConnectionError,
    InvalidConfigurationError,
    LLMResponseError,
)
from src.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
def test_health_check():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Compliance Checker API",
    }


# ---------------------------------------------------------------------------
# /analyze - happy path
# ---------------------------------------------------------------------------
def test_analyze_returns_200_with_valid_payload():
    fake_result = {
        "is_compliant": False,
        "reason": "Alocação incompatível com perfil conservador.",
        "mentioned_products": ["criptomoedas"],
    }

    with patch("src.main.analyze_text", return_value=fake_result):
        response = client.post(
            "/analyze",
            json={
                "text_to_analyze": "Recomendo 100% do patrimônio em cripto.",
                "client_profile": "conservador",
            },
        )

    assert response.status_code == 200
    assert response.json() == fake_result


# ---------------------------------------------------------------------------
# /analyze - validação Pydantic (422)
# ---------------------------------------------------------------------------
def test_analyze_returns_422_when_text_too_short():
    response = client.post(
        "/analyze",
        json={"text_to_analyze": "curto", "client_profile": "conservador"},
    )
    assert response.status_code == 422


def test_analyze_returns_422_when_field_missing():
    response = client.post(
        "/analyze",
        json={"text_to_analyze": "Texto suficientemente grande."},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# /analyze - tradução de exceções customizadas
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "exception, expected_status",
    [
        (InvalidConfigurationError("env ausente"), 503),
        (APIConnectionError("LLM offline"), 503),
        (LLMResponseError("JSON inválido"), 502),
        (RuntimeError("bug inesperado"), 500),
    ],
)
def test_analyze_translates_exceptions_to_http_status(exception, expected_status):
    with patch("src.main.analyze_text", side_effect=exception):
        response = client.post(
            "/analyze",
            json={
                "text_to_analyze": "Recomendação válida com mais de 10 chars.",
                "client_profile": "moderado",
            },
        )

    assert response.status_code == expected_status
    assert "detail" in response.json()


# ---------------------------------------------------------------------------
# /analyze - service devolve dict vazio -> tratado como APIConnectionError -> 503
# ---------------------------------------------------------------------------
def test_analyze_returns_503_when_service_returns_empty_dict():
    with patch("src.main.analyze_text", return_value={}):
        response = client.post(
            "/analyze",
            json={
                "text_to_analyze": "Recomendação válida com mais de 10 chars.",
                "client_profile": "moderado",
            },
        )

    assert response.status_code == 503
