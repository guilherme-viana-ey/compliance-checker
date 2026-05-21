"""Testes unitários de `src/services/compliance_service.py`.

Mockamos a classe `AzureModel` para que nenhuma chamada de rede real
seja feita. O foco é validar:

- O caminho principal (`instructor`) devolvendo um dict bem formado.
- O fallback (`invoke` + JSON parse) funcionando.
- A heurística final acionando uma exceção controlada.
- A tradução de erros de configuração e conexão.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.core.exceptions import (
    APIConnectionError,
    InvalidConfigurationError,
    LLMResponseError,
)
from src.services import compliance_service
from src.services.compliance_service import _LLMAnalysis, analyze_text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_mock_azure_model(
    *, structured=None, raw_content=None, structured_raises=None, invoke_raises=None
):
    """Constrói um mock de `AzureModel` com comportamento configurável."""
    mock_instance = MagicMock()
    mock_instance.deployment = "fake-deployment"

    # caminho principal: instructor
    create = mock_instance.client.chat.completions.create
    if structured_raises is not None:
        create.side_effect = structured_raises
    else:
        create.return_value = structured

    # fallback: invoke()
    if invoke_raises is not None:
        mock_instance.invoke.side_effect = invoke_raises
    elif raw_content is not None:
        choice = MagicMock()
        choice.message.content = raw_content
        invoke_response = MagicMock()
        invoke_response.choices = [choice]
        mock_instance.invoke.return_value = invoke_response

    return mock_instance


# ---------------------------------------------------------------------------
# Caminho principal: instructor devolve um _LLMAnalysis válido
# ---------------------------------------------------------------------------
def test_analyze_text_returns_dict_on_happy_path():
    structured = _LLMAnalysis(
        is_compliant=False,
        reason="Alocação concentrada em ativo de altíssimo risco.",
        mentioned_products=["criptomoedas"],
    )
    mock_model = _make_mock_azure_model(structured=structured)

    with patch.object(compliance_service, "AzureModel", return_value=mock_model):
        result = analyze_text(
            text="Recomendo 100% em cripto.",
            client_profile="conservador",
        )

    assert result == {
        "is_compliant": False,
        "reason": "Alocação concentrada em ativo de altíssimo risco.",
        "mentioned_products": ["criptomoedas"],
    }


# ---------------------------------------------------------------------------
# Fallback: instructor falha -> invoke() retorna JSON parseável
# ---------------------------------------------------------------------------
def test_analyze_text_falls_back_to_invoke_when_instructor_fails():
    mock_model = _make_mock_azure_model(
        structured_raises=RuntimeError("instructor schema mismatch"),
        raw_content=(
            '{"is_compliant": true, "reason": "OK para perfil agressivo.", '
            '"mentioned_products": ["ações small caps"]}'
        ),
    )

    with patch.object(compliance_service, "AzureModel", return_value=mock_model):
        result = analyze_text(
            text="Sugiro alocar em small caps brasileiras.",
            client_profile="agressivo",
        )

    assert result["is_compliant"] is True
    assert "perfil agressivo" in result["reason"].lower()
    assert result["mentioned_products"] == ["ações small caps"]


# ---------------------------------------------------------------------------
# Erros traduzidos em exceções customizadas
# ---------------------------------------------------------------------------
def test_analyze_text_raises_invalid_configuration_when_envs_missing():
    def _raises(*args, **kwargs):
        raise ValueError("AZURE_OPENAI_KEY ausente")

    with patch.object(compliance_service, "AzureModel", side_effect=_raises):
        with pytest.raises(InvalidConfigurationError) as exc_info:
            analyze_text(text="x" * 20, client_profile="moderado")

    assert "AZURE_OPENAI_KEY" in str(exc_info.value)


def test_analyze_text_raises_api_connection_when_invoke_fails():
    mock_model = _make_mock_azure_model(
        structured_raises=RuntimeError("instructor falhou"),
        invoke_raises=ConnectionError("DNS down"),
    )

    with patch.object(compliance_service, "AzureModel", return_value=mock_model):
        with pytest.raises(APIConnectionError):
            analyze_text(text="recomendação válida.", client_profile="moderado")


def test_analyze_text_raises_llm_response_error_on_unparseable_output():
    mock_model = _make_mock_azure_model(
        structured_raises=RuntimeError("instructor falhou"),
        raw_content="resposta totalmente sem JSON aqui",
    )

    with patch.object(compliance_service, "AzureModel", return_value=mock_model):
        with pytest.raises(LLMResponseError):
            analyze_text(text="recomendação válida.", client_profile="conservador")


def test_analyze_text_raises_llm_response_error_on_empty_output():
    mock_model = _make_mock_azure_model(
        structured_raises=RuntimeError("instructor falhou"),
        raw_content="",
    )

    with patch.object(compliance_service, "AzureModel", return_value=mock_model):
        with pytest.raises(LLMResponseError):
            analyze_text(text="recomendação válida.", client_profile="conservador")
