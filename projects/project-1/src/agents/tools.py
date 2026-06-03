"""
Ferramentas (Tools) disponíveis para o Compliance Agent.

Cada tool encapsula uma ação atômica que o agente pode executar:
- analyze_compliance  → chama a lógica RAG do Projeto 2
- move_file          → move documento para approved ou rejected_for_review
- create_alert       → registra alerta em log estruturado
- read_document      → lê e parseia o arquivo de recomendação
"""

import re
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Tuple

from ..api.schemas import AnalysisRequest, AnalysisResult
from ..services.compliance_service import analyze_recommendation

# =========================
# ✅ CONFIG DE DIRETÓRIOS
# =========================
BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_APPROVED = BASE_DIR / "data" / "output" / "approved"
OUTPUT_REJECTED = BASE_DIR / "data" / "output" / "rejected_for_review"
LOGS_DIR = BASE_DIR / "data" / "logs"

# Garante que os diretórios existem
for _dir in [OUTPUT_APPROVED, OUTPUT_REJECTED, LOGS_DIR]:
    _dir.mkdir(parents=True, exist_ok=True)

# =========================
# ✅ LOGGER
# =========================
logger = logging.getLogger("compliance_agent.tools")

# =========================
# ✅ GUARDRAILS
# =========================
MAX_FILE_SIZE_KB = 500
ALLOWED_EXTENSIONS = {".txt", ".pdf"}
PERFIL_PADRAO = "moderado"
PERFIS_VALIDOS = {"conservador", "moderado", "arrojado", "agressivo"}


# =========================
# ✅ TOOL 1: LER DOCUMENTO
# =========================
def tool_read_document(file_path: str) -> Tuple[str, str]:
    """
    Lê o arquivo de recomendação e extrai:
    - texto da recomendação
    - perfil do cliente

    Formato esperado no arquivo (qualquer ordem):
        PERFIL: conservador
        RECOMENDAÇÃO: Texto da recomendação aqui...

    Se o perfil não for encontrado, usa PERFIL_PADRAO.

    Returns:
        Tuple (recommendation_text, client_profile)

    Raises:
        ValueError: se o arquivo for inválido (tipo, tamanho, vazio)
    """
    path = Path(file_path)

    # Guardrail 1: extensão permitida
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Tipo de arquivo não suportado: {path.suffix}. "
            f"Permitidos: {ALLOWED_EXTENSIONS}"
        )

    # Guardrail 2: tamanho máximo
    size_kb = path.stat().st_size / 1024
    if size_kb > MAX_FILE_SIZE_KB:
        raise ValueError(
            f"Arquivo muito grande: {size_kb:.1f} KB "
            f"(máximo: {MAX_FILE_SIZE_KB} KB)"
        )

    # Leitura do conteúdo
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            content = "\n".join(
                page.extract_text() or "" for page in reader.pages
            ).strip()
        except Exception as e:
            raise ValueError(f"Falha ao ler PDF: {e}")
    else:
        content = path.read_text(encoding="utf-8").strip()

    # Guardrail 3: conteúdo vazio
    if not content:
        raise ValueError("Arquivo vazio ou sem texto extraível.")

    # Extração do perfil do cliente
    perfil_match = re.search(
        r"(?:PERFIL|CLIENTE|PROFILE)\s*[:=]\s*(\w+)",
        content,
        re.IGNORECASE,
    )
    if perfil_match:
        perfil_raw = perfil_match.group(1).lower()
        client_profile = perfil_raw if perfil_raw in PERFIS_VALIDOS else PERFIL_PADRAO
    else:
        client_profile = PERFIL_PADRAO
        logger.warning(
            "Perfil do cliente não encontrado em '%s'. "
            "Usando perfil padrão: '%s'.",
            path.name, PERFIL_PADRAO
        )

    # Extração do texto da recomendação
    rec_match = re.search(
        r"(?:RECOMENDA[ÇC][ÃA]O|RECOMENDACAO|RECOMMENDATION)\s*[:=]\s*(.*)",
        content,
        re.IGNORECASE | re.DOTALL,
    )
    if rec_match:
        recommendation_text = rec_match.group(1).strip()
    else:
        # Usa o conteúdo completo como recomendação
        recommendation_text = content

    logger.info(
        "Documento lido: '%s' | Perfil: '%s' | Tamanho: %.1f KB",
        path.name, client_profile, size_kb
    )

    return recommendation_text, client_profile


# =========================
# ✅ TOOL 2: ANALISAR COMPLIANCE
# =========================
def tool_analyze_compliance(
    text: str,
    client_profile: str,
) -> AnalysisResult:
    """
    Invoca a pipeline RAG do Projeto 2 para analisar a conformidade.

    Args:
        text: Texto da recomendação de investimento.
        client_profile: Perfil de risco do cliente.

    Returns:
        AnalysisResult com is_compliant, reason, mentioned_products e sources.
    """
    request = AnalysisRequest(text=text, client_profile=client_profile)
    result = analyze_recommendation(request)

    logger.info(
        "Análise concluída | is_compliant=%s | produtos=%s",
        result.is_compliant, result.mentioned_products
    )

    return result


# =========================
# ✅ TOOL 3: MOVER ARQUIVO
# =========================
def tool_move_file(file_path: str, destination: str) -> str:
    """
    Move o arquivo de recomendação para o diretório de destino.

    Args:
        file_path: Caminho absoluto do arquivo de origem.
        destination: 'approved' ou 'rejected_for_review'.

    Returns:
        Caminho absoluto do arquivo no destino.
    """
    src = Path(file_path)

    if destination == "approved":
        dst_dir = OUTPUT_APPROVED
    else:
        dst_dir = OUTPUT_REJECTED

    # Evita sobrescrita: adiciona timestamp se já existir
    dst = dst_dir / src.name
    if dst.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = dst_dir / f"{src.stem}_{ts}{src.suffix}"

    shutil.move(str(src), str(dst))

    logger.info("Arquivo movido: '%s' → '%s'", src.name, dst_dir.name)

    return str(dst)


# =========================
# ✅ TOOL 4: CRIAR ALERTA
# =========================
def tool_create_alert(
    file_name: str,
    reason: str,
    mentioned_products: list,
    sources: list,
) -> str:
    """
    Registra um alerta estruturado em log para casos não-conformes.
    Simula notificação para a equipe de compliance.

    Args:
        file_name: Nome do arquivo que gerou o alerta.
        reason: Justificativa da não-conformidade.
        mentioned_products: Produtos citados na recomendação.
        sources: Fontes regulatórias que embasaram a decisão.

    Returns:
        Mensagem de alerta registrada.
    """
    log_file = LOGS_DIR / "alerts.log"
    timestamp = datetime.now().isoformat(timespec="seconds")

    sources_str = ", ".join(
        f"{s.get('source_document', '?')}#{s.get('source_chunk_id', '?')}"
        for s in sources
    ) if sources else "N/A"

    alert_lines = [
        f"[{timestamp}] ⚠️  ALERTA DE NÃO-CONFORMIDADE",
        f"  Arquivo  : {file_name}",
        f"  Motivo   : {reason}",
        f"  Produtos : {', '.join(mentioned_products) or 'N/A'}",
        f"  Fontes   : {sources_str}",
        f"  Ação     : Encaminhado para revisão manual em rejected_for_review/",
        "-" * 60,
    ]
    alert_msg = "\n".join(alert_lines)

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(alert_msg + "\n")

    logger.warning("ALERTA registrado para '%s'", file_name)

    return alert_msg