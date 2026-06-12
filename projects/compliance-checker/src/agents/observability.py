"""
Observabilidade — Compliance Checker

Duas camadas:
  1. LangSmith  → tracing automático de todas as chamadas LangGraph + LLM
  2. Prometheus → métricas de negócio expostas em GET /metrics

Métricas expostas:
  - compliance_documents_total        (counter)  → total processado por ação
  - compliance_analysis_duration      (histogram) → tempo por análise em segundos
  - compliance_automation_rate        (gauge)     → taxa de automação (0-100)
  - compliance_tokens_used_total      (counter)   → tokens consumidos no LLM
  - compliance_errors_total           (counter)   → total de erros críticos
"""

import logging
import os
import time
from functools import wraps
from pathlib import Path
from typing import Callable

logger = logging.getLogger("compliance_agent.observability")


# =========================
# ✅ LANGSMITH — TRACING
# =========================
def setup_langsmith():
    """
    Ativa o tracing do LangSmith para todas as chamadas LangGraph e LLM.

    Requer no .env:
        LANGCHAIN_API_KEY=ls__...
        LANGCHAIN_TRACING_V2=true
        LANGCHAIN_PROJECT=compliance-checker

    Todos os traces ficam visíveis em: https://smith.langchain.com
    """
    api_key = os.getenv("LANGCHAIN_API_KEY")
    tracing = os.getenv("LANGCHAIN_TRACING_V2", "false").lower()

    if not api_key or tracing != "true":
        logger.info(
            "LangSmith não configurado. "
            "Adicione LANGCHAIN_API_KEY e LANGCHAIN_TRACING_V2=true no .env para ativar."
        )
        return False

    project = os.getenv("LANGCHAIN_PROJECT", "compliance-checker")
    logger.info("LangSmith ativo | Projeto: %s", project)
    return True


# =========================
# ✅ PROMETHEUS — MÉTRICAS
# =========================
def _init_prometheus():
    """
    Inicializa as métricas Prometheus.
    Retorna None se prometheus_client não estiver instalado.
    """
    try:
        from prometheus_client import Counter, Gauge, Histogram
        return {
            # Total de documentos processados por ação
            "documents_total": Counter(
                "compliance_documents_total",
                "Total de documentos processados pelo agente",
                ["action"],  # labels: APROVADO, REJEITADO_PARA_REVISAO, ERRO_CRITICO
            ),
            # Duração de cada análise
            "analysis_duration": Histogram(
                "compliance_analysis_duration_seconds",
                "Tempo de análise por documento em segundos",
                buckets=[1, 2, 5, 10, 20, 30, 60],
            ),
            # Taxa de automação atual (0 a 100)
            "automation_rate": Gauge(
                "compliance_automation_rate",
                "Taxa de automação percentual (documentos sem erro / total)",
            ),
            # Total de tokens consumidos
            "tokens_total": Counter(
                "compliance_tokens_used_total",
                "Total de tokens consumidos nas chamadas ao LLM",
                ["type"],  # labels: prompt, completion
            ),
            # Erros críticos
            "errors_total": Counter(
                "compliance_errors_total",
                "Total de erros críticos no agente",
                ["stage"],  # labels: read_document, analyze, move_file
            ),
        }
    except ImportError:
        logger.warning(
            "prometheus_client não instalado. "
            "Rode: pip install prometheus-client"
        )
        return None


# Instância global das métricas
_metrics = None


def get_metrics():
    """Retorna (ou inicializa) as métricas Prometheus."""
    global _metrics
    if _metrics is None:
        _metrics = _init_prometheus()
    return _metrics


# =========================
# ✅ HELPERS DE REGISTRO
# =========================
def record_document_processed(action: str, duration_seconds: float):
    """
    Registra uma análise concluída.

    Args:
        action: 'APROVADO', 'REJEITADO_PARA_REVISAO' ou 'ERRO_CRITICO'
        duration_seconds: tempo total da análise
    """
    m = get_metrics()
    if m is None:
        return

    m["documents_total"].labels(action=action).inc()
    m["analysis_duration"].observe(duration_seconds)


def record_tokens_used(prompt_tokens: int, completion_tokens: int):
    """
    Registra tokens consumidos em uma chamada ao LLM.

    Args:
        prompt_tokens: tokens no prompt (entrada)
        completion_tokens: tokens na resposta (saída)
    """
    m = get_metrics()
    if m is None:
        return

    if prompt_tokens:
        m["tokens_total"].labels(type="prompt").inc(prompt_tokens)
    if completion_tokens:
        m["tokens_total"].labels(type="completion").inc(completion_tokens)


def record_error(stage: str):
    """
    Registra um erro crítico em uma etapa do agente.

    Args:
        stage: 'read_document', 'analyze_compliance', 'move_file'
    """
    m = get_metrics()
    if m is None:
        return

    m["errors_total"].labels(stage=stage).inc()


def update_automation_rate(automated: int, total: int):
    """
    Atualiza o gauge de taxa de automação.

    Args:
        automated: documentos processados sem erro
        total: total de documentos no lote
    """
    m = get_metrics()
    if m is None:
        return

    rate = (automated / total * 100) if total > 0 else 0
    m["automation_rate"].set(rate)


# =========================
# ✅ DECORADOR DE TIMING
# =========================
def timed_stage(stage_name: str):
    """
    Decorador que mede o tempo de execução de uma função
    e registra erros automaticamente.

    Uso:
        @timed_stage("analyze_compliance")
        def node_analyze_compliance(state):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start
                logger.debug("%s concluído em %.2fs", stage_name, duration)
                return result
            except Exception as e:
                record_error(stage=stage_name)
                logger.error("%s falhou após %.2fs: %s", stage_name, time.time() - start, e)
                raise
        return wrapper
    return decorator