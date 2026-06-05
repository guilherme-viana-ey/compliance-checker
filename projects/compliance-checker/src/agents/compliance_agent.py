"""
Compliance Agent — Orquestrador LangGraph.

Grafo de estados:
    START
      │
      ▼
  read_document       ← lê e valida o arquivo
      │
      ▼
  analyze_compliance  ← invoca pipeline RAG (Projeto 2)
      │
      ├── is_compliant=True  ──► approve_document ──► END
      │
      └── is_compliant=False ──► reject_document  ──► END
          (+ error)

Cada nó registra logs estruturados para rastreabilidade completa.
"""

import logging
import time
from datetime import datetime
from typing import List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from .tools import (
    tool_analyze_compliance,
    tool_create_alert,
    tool_move_file,
    tool_read_document,
)

# =========================
# ✅ LOGGER
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("compliance_agent")


# =========================
# ✅ ESTADO DO AGENTE
# =========================
class ComplianceState(TypedDict):
    """
    Estado compartilhado entre todos os nós do grafo.
    Cada nó lê e escreve nesse dicionário.
    """
    # Input
    file_path: str
    file_name: str

    # Extraído do documento
    recommendation_text: str
    client_profile: str

    # Resultado da análise RAG
    is_compliant: Optional[bool]
    reason: str
    mentioned_products: List[str]
    sources: List[dict]

    # Resultado da ação
    action_taken: str
    destination_path: str

    # Controle de execução
    error: Optional[str]
    execution_logs: List[str]
    started_at: str
    finished_at: str
    duration_seconds: float


# =========================
# ✅ NÓ 1: LER DOCUMENTO
# =========================
def node_read_document(state: ComplianceState) -> ComplianceState:
    """
    Lê o arquivo de recomendação, valida e extrai texto e perfil do cliente.
    Em caso de erro, marca o estado com error para rejeição automática.
    """
    log_entry = f"[read_document] Lendo arquivo: {state['file_name']}"
    logger.info(log_entry)

    try:
        text, profile = tool_read_document(state["file_path"])
        return {
            **state,
            "recommendation_text": text,
            "client_profile": profile,
            "execution_logs": state["execution_logs"] + [log_entry],
        }
    except Exception as e:
        error_msg = f"[read_document] ERRO ao ler '{state['file_name']}': {e}"
        logger.error(error_msg)
        return {
            **state,
            "recommendation_text": "",
            "client_profile": "desconhecido",
            "error": str(e),
            "execution_logs": state["execution_logs"] + [log_entry, error_msg],
        }


# =========================
# ✅ NÓ 2: ANALISAR COMPLIANCE
# =========================
def node_analyze_compliance(state: ComplianceState) -> ComplianceState:
    """
    Invoca a pipeline RAG do Projeto 2 para analisar a conformidade.
    Pula a análise se houver erro anterior (arquivo inválido).
    """
    if state.get("error"):
        log_entry = "[analyze_compliance] Pulando análise devido a erro anterior."
        logger.warning(log_entry)
        return {
            **state,
            "is_compliant": False,
            "reason": f"Arquivo inválido: {state['error']}",
            "mentioned_products": [],
            "sources": [],
            "execution_logs": state["execution_logs"] + [log_entry],
        }

    log_entry = (
        f"[analyze_compliance] Analisando recomendação | "
        f"perfil='{state['client_profile']}'"
    )
    logger.info(log_entry)

    try:
        result = tool_analyze_compliance(
            text=state["recommendation_text"],
            client_profile=state["client_profile"],
        )

        # Serializa sources para dict (compatível com TypedDict)
        sources_as_dict = [
            {
                "source_document": s.source_document,
                "source_chunk_id": s.source_chunk_id,
                "relevance_score": s.relevance_score,
                "excerpt": s.excerpt,
            }
            for s in result.sources
        ]

        result_log = (
            f"[analyze_compliance] Resultado: is_compliant={result.is_compliant} | "
            f"produtos={result.mentioned_products}"
        )
        logger.info(result_log)

        return {
            **state,
            "is_compliant": result.is_compliant,
            "reason": result.reason,
            "mentioned_products": result.mentioned_products,
            "sources": sources_as_dict,
            "execution_logs": state["execution_logs"] + [log_entry, result_log],
        }

    except Exception as e:
        error_msg = f"[analyze_compliance] ERRO na análise: {e}"
        logger.error(error_msg)
        return {
            **state,
            "is_compliant": False,
            "reason": f"Falha na análise de compliance: {e}",
            "mentioned_products": [],
            "sources": [],
            "error": str(e),
            "execution_logs": state["execution_logs"] + [log_entry, error_msg],
        }


# =========================
# ✅ NÓ 3A: APROVAR DOCUMENTO
# =========================
def node_approve_document(state: ComplianceState) -> ComplianceState:
    """
    Move o documento para data/output/approved.
    Registra log de aprovação.
    """
    log_entry = f"[approve] ✅ Aprovando '{state['file_name']}'"
    logger.info(log_entry)

    try:
        dst = tool_move_file(state["file_path"], "approved")
        finished = datetime.now().isoformat(timespec="seconds")
        duration = time.time() - datetime.fromisoformat(state["started_at"]).timestamp()

        action_log = f"[approve] Arquivo movido para: {dst}"
        logger.info(action_log)

        return {
            **state,
            "action_taken": "APROVADO",
            "destination_path": dst,
            "finished_at": finished,
            "duration_seconds": round(duration, 2),
            "execution_logs": state["execution_logs"] + [log_entry, action_log],
        }

    except Exception as e:
        error_msg = f"[approve] ERRO ao mover arquivo: {e}"
        logger.error(error_msg)
        return {
            **state,
            "action_taken": "ERRO_APROVACAO",
            "error": str(e),
            "execution_logs": state["execution_logs"] + [log_entry, error_msg],
        }


# =========================
# ✅ NÓ 3B: REJEITAR DOCUMENTO
# =========================
def node_reject_document(state: ComplianceState) -> ComplianceState:
    """
    Move o documento para data/output/rejected_for_review.
    Cria alerta estruturado no log de alertas.
    """
    log_entry = f"[reject] ⚠️  Rejeitando '{state['file_name']}' para revisão manual"
    logger.warning(log_entry)

    try:
        # Move o arquivo
        dst = tool_move_file(state["file_path"], "rejected_for_review")

        # Cria alerta
        alert = tool_create_alert(
            file_name=state["file_name"],
            reason=state["reason"],
            mentioned_products=state["mentioned_products"],
            sources=state["sources"],
        )

        finished = datetime.now().isoformat(timespec="seconds")
        duration = time.time() - datetime.fromisoformat(state["started_at"]).timestamp()

        action_log = f"[reject] Arquivo movido para rejected_for_review | Alerta criado"
        logger.warning(action_log)

        return {
            **state,
            "action_taken": "REJEITADO_PARA_REVISAO",
            "destination_path": dst,
            "finished_at": finished,
            "duration_seconds": round(duration, 2),
            "execution_logs": state["execution_logs"] + [log_entry, action_log, alert],
        }

    except Exception as e:
        error_msg = f"[reject] ERRO ao rejeitar arquivo: {e}"
        logger.error(error_msg)
        return {
            **state,
            "action_taken": "ERRO_REJEICAO",
            "error": str(e),
            "execution_logs": state["execution_logs"] + [log_entry, error_msg],
        }


# =========================
# ✅ ROTEADOR CONDICIONAL
# =========================
def route_compliance_decision(state: ComplianceState) -> str:
    """
    Decide o próximo nó com base no resultado da análise.
    Qualquer erro também leva à rejeição (mais seguro para compliance).
    """
    if state.get("error") or not state.get("is_compliant"):
        return "reject"
    return "approve"


# =========================
# ✅ CONSTRUÇÃO DO GRAFO
# =========================
def build_agent() -> StateGraph:
    """
    Constrói e compila o grafo LangGraph do Compliance Agent.

    Grafo:
        read_document → analyze_compliance → [approve | reject] → END
    """
    workflow = StateGraph(ComplianceState)

    # Nós
    workflow.add_node("read_document", node_read_document)
    workflow.add_node("analyze_compliance", node_analyze_compliance)
    workflow.add_node("approve", node_approve_document)
    workflow.add_node("reject", node_reject_document)

    # Fluxo
    workflow.set_entry_point("read_document")
    workflow.add_edge("read_document", "analyze_compliance")
    workflow.add_conditional_edges(
        "analyze_compliance",
        route_compliance_decision,
        {
            "approve": "approve",
            "reject": "reject",
        },
    )
    workflow.add_edge("approve", END)
    workflow.add_edge("reject", END)

    return workflow.compile()


# Instância única do agente (reutilizável)
agent = build_agent()


# =========================
# ✅ FUNÇÃO DE EXECUÇÃO
# =========================
def run_agent(file_path: str) -> ComplianceState:
    """
    Executa o agente para um único arquivo de recomendação.

    Args:
        file_path: Caminho absoluto do arquivo a processar.

    Returns:
        Estado final do agente com logs e resultado da ação.
    """
    file_path = str(file_path)
    file_name = Path(file_path).name
    started_at = datetime.now().isoformat(timespec="seconds")

    logger.info("=" * 60)
    logger.info("INICIANDO ANÁLISE | Arquivo: %s", file_name)
    logger.info("=" * 60)

    # Estado inicial
    initial_state: ComplianceState = {
        "file_path": file_path,
        "file_name": file_name,
        "recommendation_text": "",
        "client_profile": "",
        "is_compliant": None,
        "reason": "",
        "mentioned_products": [],
        "sources": [],
        "action_taken": "",
        "destination_path": "",
        "error": None,
        "execution_logs": [],
        "started_at": started_at,
        "finished_at": "",
        "duration_seconds": 0.0,
    }

    # Executa o grafo
    final_state = agent.invoke(initial_state)

    # Log de encerramento
    logger.info(
        "ANÁLISE CONCLUÍDA | Arquivo: %s | Ação: %s | Duração: %.2fs",
        file_name,
        final_state.get("action_taken", "N/A"),
        final_state.get("duration_seconds", 0.0),
    )
    logger.info("=" * 60)

    return final_state


# Importação necessária nos nós
from pathlib import Path  # noqa: E402