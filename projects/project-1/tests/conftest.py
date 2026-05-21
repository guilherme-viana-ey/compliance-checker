"""Fixtures compartilhadas e configuração de ambiente para os testes.

Aqui injetamos variáveis de ambiente "fake" para que a instanciação
do `AzureModel` não falhe durante os testes (mesmo quando ela ainda
ocorrer dentro de mocks).
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _fake_env(monkeypatch):
    """Injeta variáveis de ambiente fictícias para evitar dependência do .env."""
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://fake.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_KEY", "fake-key")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-06-01")
    monkeypatch.setenv("AZURE_DEPLOYMENT_NAME", "fake-deployment")
    yield
