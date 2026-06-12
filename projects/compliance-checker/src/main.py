"""Compliance Checker API — ponto de entrada FastAPI.

Endpoints:
  Etapa 1 e 2:
    GET  /              → health check
    POST /analyze       → análise RAG de uma recomendação

  Etapa 3 (Agente):
    POST /agent/process-file    → upload e processamento via agente
    POST /agent/run-batch       → processa data/input/ em background
    GET  /agent/metrics         → métricas da última execução batch
    GET  /agent/status          → status do watcher

  Bônus (Observabilidade):
    GET  /metrics               → métricas Prometheus (scraping)
"""

import json
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse

from .api.schemas import AnalysisRequest, AnalysisResult
from .services.compliance_service import analyze_recommendation

# =========================
# ✅ CONFIG
# =========================
BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = BASE_DIR / "data" / "input"
LOGS_DIR  = BASE_DIR / "data" / "logs"

_watcher_thread: threading.Thread = None
_watcher_active: bool = False


# =========================
# ✅ LIFESPAN
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _watcher_thread, _watcher_active

    # ── LangSmith tracing ──────────────────────────────────
    try:
        from .agents.observability import setup_langsmith
        setup_langsmith()
    except Exception as e:
        print(f"⚠️  Observabilidade não iniciada: {e}")

    # ── Watcher em background ──────────────────────────────
    try:
        from .agents.watcher import start_watcher
        INPUT_DIR.mkdir(parents=True, exist_ok=True)
        _watcher_thread = threading.Thread(
            target=start_watcher,
            args=(INPUT_DIR,),
            daemon=True,
            name="compliance-watcher",
        )
        _watcher_thread.start()
        _watcher_active = True
        print("✅ Watcher iniciado — monitorando:", INPUT_DIR)
    except Exception as e:
        print(f"⚠️  Watcher não iniciado: {e}")
        _watcher_active = False

    yield

    _watcher_active = False
    print("🛑 API encerrada.")


# =========================
# ✅ APP
# =========================
app = FastAPI(
    title="Compliance Checker API",
    description=(
        "Sistema autônomo de análise de conformidade para o mercado financeiro brasileiro. "
        "Analisa recomendações de investimento contra documentos regulatórios oficiais "
        "(ANBIMA, CVM) usando RAG com re-ranking."
    ),
    version="3.0.0",
    lifespan=lifespan,
)


# =========================
# ✅ Etapa 1 e 2
# =========================
@app.get("/", tags=["health"])
def health_check():
    return {
        "status": "ok",
        "service": "Compliance Checker API",
        "version": "3.0.0",
        "watcher_active": _watcher_active,
    }


@app.post("/analyze", response_model=AnalysisResult, tags=["compliance"])
def analyze(request: AnalysisRequest) -> AnalysisResult:
    """Analisa uma recomendação de investimento via RAG."""
    return analyze_recommendation(request)


# =========================
# ✅ Etapa 3 — AGENTE
# =========================
@app.post("/agent/process-file", tags=["agent"])
async def process_file(file: UploadFile = File(...)):
    """
    Recebe um arquivo de recomendação via upload e processa via agente.
    Retorna o resultado completo incluindo ação tomada e fontes usadas.
    """
    from .agents.compliance_agent import run_agent
    from .agents.observability import record_document_processed

    allowed = {".txt", ".pdf"}
    suffix = Path(file.filename).suffix.lower()
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Extensão não suportada: {suffix}. Permitidas: {allowed}",
        )

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    file_path = INPUT_DIR / file.filename
    content = await file.read()
    file_path.write_bytes(content)

    try:
        state = run_agent(str(file_path))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao processar arquivo: {e}")

    # Registra métrica
    record_document_processed(
        action=state.get("action_taken", "ERRO_CRITICO"),
        duration_seconds=state.get("duration_seconds", 0.0),
    )

    return {
        "file": state["file_name"],
        "action": state["action_taken"],
        "is_compliant": state["is_compliant"],
        "reason": state["reason"],
        "mentioned_products": state["mentioned_products"],
        "client_profile": state["client_profile"],
        "duration_seconds": state["duration_seconds"],
        "destination": state["destination_path"],
        "sources": state["sources"],
        "error": state.get("error"),
    }


@app.post("/agent/run-batch", tags=["agent"])
def run_batch_endpoint(background_tasks: BackgroundTasks):
    """Processa todos os arquivos em data/input/ em background."""
    from .agents.runner import run_batch

    files = list(INPUT_DIR.glob("*.txt")) + list(INPUT_DIR.glob("*.pdf"))
    if not files:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum arquivo encontrado em {INPUT_DIR}",
        )

    background_tasks.add_task(run_batch)

    return {
        "status": "batch iniciado",
        "files_found": len(files),
        "message": "Processamento em background. Consulte GET /agent/metrics para o resultado.",
    }


@app.get("/agent/metrics", tags=["agent"])
def get_agent_metrics():
    """Retorna as métricas da última execução batch (JSON)."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_files = sorted(LOGS_DIR.glob("execution_*.json"), reverse=True)

    if not log_files:
        raise HTTPException(
            status_code=404,
            detail="Nenhuma execução batch encontrada. Rode POST /agent/run-batch primeiro.",
        )

    with open(log_files[0], encoding="utf-8") as f:
        data = json.load(f)

    return {"last_execution": log_files[0].name, **data}


@app.get("/agent/status", tags=["agent"])
def get_status():
    """Status atual do watcher e contagem de arquivos por diretório."""
    def count_files(path: Path) -> int:
        return len(list(path.glob("*.*"))) if path.exists() else 0

    approved_dir = BASE_DIR / "data" / "output" / "approved"
    rejected_dir = BASE_DIR / "data" / "output" / "rejected_for_review"
    log_files    = sorted(LOGS_DIR.glob("execution_*.json"), reverse=True) if LOGS_DIR.exists() else []

    return {
        "watcher_active": _watcher_active,
        "monitoring_directory": str(INPUT_DIR),
        "files_waiting": count_files(INPUT_DIR),
        "files_approved": count_files(approved_dir),
        "files_rejected": count_files(rejected_dir),
        "total_executions": len(log_files),
        "last_execution": log_files[0].name if log_files else None,
    }


# =========================
# ✅ BÔNUS — PROMETHEUS METRICS
# =========================
@app.get("/metrics", tags=["observability"], response_class=PlainTextResponse)
def prometheus_metrics():
    """
    Endpoint de scraping do Prometheus.
    Expõe todas as métricas no formato texto do Prometheus.

    Métricas disponíveis:
      - compliance_documents_total        (por ação)
      - compliance_analysis_duration      (histograma em segundos)
      - compliance_automation_rate        (gauge 0-100)
      - compliance_tokens_used_total      (por tipo: prompt/completion)
      - compliance_errors_total           (por etapa)
    """
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
        return PlainTextResponse(
            content=generate_latest().decode("utf-8"),
            media_type=CONTENT_TYPE_LATEST,
        )
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="prometheus_client não instalado. Rode: pip install prometheus-client",
        )