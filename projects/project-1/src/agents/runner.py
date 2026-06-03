"""
Runner — Ponto de entrada do Compliance Agent.

Suporta dois modos:
  1. BATCH  : processa todos os arquivos existentes em data/input/
  2. WATCH  : monitora data/input/ em tempo real (modo daemon)

Ao final do modo batch, exibe o Indicador de Automação.

Uso:
    python -m src.agents.runner --mode batch
    python -m src.agents.runner --mode watch
    python -m src.agents.runner           (padrão: batch)
"""

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

from .compliance_agent import run_agent
from .watcher import start_watcher

# =========================
# ✅ CONFIG
# =========================
BASE_DIR = Path(__file__).resolve().parents[2]
INPUT_DIR = BASE_DIR / "data" / "input"
LOGS_DIR = BASE_DIR / "data" / "logs"
ALLOWED_EXTENSIONS = {".txt", ".pdf"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("compliance_agent.runner")


# =========================
# ✅ MODO BATCH
# =========================
def run_batch():
    """
    Processa todos os arquivos existentes em data/input/.
    Ao final, calcula e exibe o Indicador de Automação.
    """
    files = [
        f for f in INPUT_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in ALLOWED_EXTENSIONS
        and not f.name.startswith((".", "~", "_"))
    ]

    if not files:
        logger.warning("Nenhum arquivo encontrado em %s", INPUT_DIR)
        return

    logger.info("Modo BATCH | %d arquivo(s) encontrado(s)", len(files))

    results = []
    for file_path in files:
        logger.info("Processando: %s", file_path.name)
        try:
            state = run_agent(str(file_path))
            results.append({
                "file": file_path.name,
                "action": state.get("action_taken", "N/A"),
                "is_compliant": state.get("is_compliant"),
                "error": state.get("error"),
                "duration_seconds": state.get("duration_seconds", 0.0),
                "client_profile": state.get("client_profile", "N/A"),
                "mentioned_products": state.get("mentioned_products", []),
            })
        except Exception as e:
            logger.error("Falha crítica em '%s': %s", file_path.name, e)
            results.append({
                "file": file_path.name,
                "action": "ERRO_CRITICO",
                "is_compliant": None,
                "error": str(e),
                "duration_seconds": 0.0,
                "client_profile": "N/A",
                "mentioned_products": [],
            })

    _print_automation_report(results)
    _save_execution_log(results)


# =========================
# ✅ INDICADOR DE AUTOMAÇÃO
# =========================
def _print_automation_report(results: list):
    """
    Calcula e exibe o Indicador de Automação (Antes vs. Depois).

    Lógica:
    - Automatizado com sucesso: ação é APROVADO ou REJEITADO_PARA_REVISAO (sem erro crítico)
    - Requer intervenção: ação ERRO_CRITICO ou ERRO_APROVACAO ou ERRO_REJEICAO
    - Casos rejeitados ainda são automáticos — o alerta já foi criado e o arquivo movido
    """
    total = len(results)
    if total == 0:
        return

    automatizados = sum(
        1 for r in results
        if r["action"] in ("APROVADO", "REJEITADO_PARA_REVISAO")
    )
    aprovados = sum(1 for r in results if r["action"] == "APROVADO")
    rejeitados = sum(1 for r in results if r["action"] == "REJEITADO_PARA_REVISAO")
    erros = total - automatizados

    taxa_automacao = (automatizados / total) * 100
    taxa_manual = 100 - taxa_automacao

    # Estimativa de tempo poupado
    # Premissa: análise manual leva 15 min por documento
    MINUTOS_POR_ANALISE_MANUAL = 15
    minutos_poupados = automatizados * MINUTOS_POR_ANALISE_MANUAL
    horas_poupadas = minutos_poupados / 60

    tempo_medio = (
        sum(r["duration_seconds"] for r in results) / total
        if total > 0 else 0
    )

    sep = "=" * 60
    print(f"\n{sep}")
    print("  INDICADOR DE AUTOMAÇÃO — COMPLIANCE AGENT")
    print(sep)
    print(f"  Total de documentos processados : {total}")
    print(f"  Aprovados automaticamente        : {aprovados}")
    print(f"  Rejeitados (c/ alerta criado)    : {rejeitados}")
    print(f"  Erros (requer intervenção)        : {erros}")
    print(sep)
    print(f"  Taxa de automação                : {taxa_automacao:.1f}%")
    print(f"  Taxa de intervenção manual       : {taxa_manual:.1f}%")
    print(sep)
    print("  GANHO DE EFICIÊNCIA ESTIMADO")
    print(f"  Antes  : 100% manual → {total * MINUTOS_POR_ANALISE_MANUAL} min de trabalho")
    print(f"  Depois : {taxa_manual:.1f}% manual → {erros * MINUTOS_POR_ANALISE_MANUAL} min de trabalho")
    print(f"  Tempo poupado : {minutos_poupados} min ({horas_poupadas:.1f}h) neste lote")
    print(f"  Tempo médio por análise          : {tempo_medio:.2f}s")
    print(sep)
    print("  RESULTADOS POR ARQUIVO")
    print(sep)
    for r in results:
        status_icon = "✅" if r["action"] == "APROVADO" else "⚠️ " if r["action"] == "REJEITADO_PARA_REVISAO" else "❌"
        print(f"  {status_icon} {r['file']:<40} → {r['action']}")
    print(sep + "\n")


# =========================
# ✅ LOG DE EXECUÇÃO JSON
# =========================
def _save_execution_log(results: list):
    """
    Salva o log de execução em JSON para auditoria.
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"execution_{ts}.json"

    total = len(results)
    automatizados = sum(
        1 for r in results
        if r["action"] in ("APROVADO", "REJEITADO_PARA_REVISAO")
    )

    payload = {
        "timestamp": datetime.now().isoformat(),
        "total_documents": total,
        "automated": automatizados,
        "manual_intervention_required": total - automatizados,
        "automation_rate_pct": round((automatizados / total * 100) if total else 0, 2),
        "results": results,
    }

    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    logger.info("Log de execução salvo em: %s", log_file)


# =========================
# ✅ ENTRYPOINT
# =========================
def main():
    parser = argparse.ArgumentParser(
        description="Compliance Agent Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modos:
  batch  → Processa todos os arquivos em data/input/ e exibe relatório
  watch  → Monitora data/input/ em tempo real (daemon)

Exemplos:
  python -m src.agents.runner --mode batch
  python -m src.agents.runner --mode watch
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["batch", "watch"],
        default="batch",
        help="Modo de execução (padrão: batch)",
    )
    args = parser.parse_args()

    if args.mode == "watch":
        logger.info("Iniciando modo WATCH...")
        start_watcher(INPUT_DIR)
    else:
        logger.info("Iniciando modo BATCH...")
        run_batch()


if __name__ == "__main__":
    main()