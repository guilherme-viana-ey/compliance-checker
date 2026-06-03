"""
File Watcher — Monitora data/input/ e dispara o Compliance Agent.

Usa a biblioteca `watchdog` para detectar novos arquivos em tempo real.
Para cada novo arquivo detectado, executa o agente de compliance.

Uso:
    python -m src.agents.watcher
    ou via runner.py
"""

import logging
import time
from pathlib import Path

from watchdog.events import FileCreatedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .compliance_agent import run_agent

# =========================
# ✅ CONFIG
# =========================
BASE_DIR = Path(__file__).resolve().parents[2]
INPUT_DIR = BASE_DIR / "data" / "input"
ALLOWED_EXTENSIONS = {".txt", ".pdf"}

logger = logging.getLogger("compliance_agent.watcher")

# Delay para garantir que o arquivo foi completamente escrito
# antes de processá-lo (evita leitura parcial)
FILE_SETTLE_DELAY = 1.5


# =========================
# ✅ EVENT HANDLER
# =========================
class RecommendationHandler(FileSystemEventHandler):
    """
    Trata eventos de criação de arquivos no diretório monitorado.
    Apenas extensões permitidas disparam o agente.
    """

    def on_created(self, event: FileCreatedEvent):
        if event.is_directory:
            return

        file_path = Path(event.src_path)

        # Guardrail: extensão permitida
        if file_path.suffix.lower() not in ALLOWED_EXTENSIONS:
            logger.debug(
                "Arquivo ignorado (extensão não suportada): %s", file_path.name
            )
            return

        # Guardrail: arquivos ocultos e temporários
        if file_path.name.startswith((".", "~", "_")):
            logger.debug("Arquivo ignorado (temporário/oculto): %s", file_path.name)
            return

        logger.info("Novo arquivo detectado: %s", file_path.name)

        # Aguarda o arquivo ser completamente escrito
        time.sleep(FILE_SETTLE_DELAY)

        # Verifica se o arquivo ainda existe (pode ter sido movido)
        if not file_path.exists():
            logger.warning(
                "Arquivo desapareceu antes de ser processado: %s", file_path.name
            )
            return

        # Dispara o agente
        try:
            final_state = run_agent(str(file_path))
            logger.info(
                "Processamento concluído | %s → %s",
                file_path.name,
                final_state.get("action_taken", "N/A"),
            )
        except Exception as e:
            logger.error(
                "Falha crítica ao processar '%s': %s", file_path.name, e
            )


# =========================
# ✅ WATCHER PRINCIPAL
# =========================
def start_watcher(input_dir: Path = INPUT_DIR):
    """
    Inicia o monitoramento do diretório de entrada.
    Bloqueia até receber KeyboardInterrupt (Ctrl+C).

    Args:
        input_dir: Diretório a monitorar (padrão: data/input/).
    """
    input_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("Compliance Agent — Watcher iniciado")
    logger.info("Monitorando: %s", input_dir)
    logger.info("Extensões aceitas: %s", ALLOWED_EXTENSIONS)
    logger.info("Pressione Ctrl+C para encerrar.")
    logger.info("=" * 60)

    handler = RecommendationHandler()
    observer = Observer()
    observer.schedule(handler, str(input_dir), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Encerrando watcher...")
        observer.stop()

    observer.join()
    logger.info("Watcher encerrado.")


# =========================
# ✅ ENTRYPOINT
# =========================
if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    start_watcher()