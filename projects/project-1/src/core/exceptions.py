"""Exceções customizadas do domínio Compliance Checker.

Cada exceção representa uma falha de negócio ou infraestrutura
específica, permitindo que a camada de API (`src/main.py`) traduza
cada caso em um status HTTP apropriado.

Hierarquia:

    ComplianceCheckerError                (base)
        InvalidConfigurationError         -> 503 Service Unavailable
        APIConnectionError                -> 503 Service Unavailable
        LLMResponseError                  -> 502 Bad Gateway
"""


class ComplianceCheckerError(Exception):
    """Classe base de todas as exceções de domínio do projeto."""


class InvalidConfigurationError(ComplianceCheckerError):
    """Configuração obrigatória ausente ou inválida (ex.: env vars)."""


class APIConnectionError(ComplianceCheckerError):
    """Falha ao se comunicar com um serviço externo (ex.: Azure OpenAI)."""


class LLMResponseError(ComplianceCheckerError):
    """O LLM respondeu, mas a resposta não pôde ser interpretada."""
