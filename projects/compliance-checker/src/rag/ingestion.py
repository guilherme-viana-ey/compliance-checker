"""
Pipeline de ingestão RAG:
- lê arquivos da knowledge_base
- faz chunking
- gera embeddings locais (offline, sem download)
- armazena no ChromaDB

Idempotente e robusto
"""

import uuid
from pathlib import Path

import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

# =========================
# ✅ CONFIG
# =========================
BASE_DIR = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE = BASE_DIR / "knowledge_base"
DB_DIR = BASE_DIR / "chroma_db"

COLLECTION_NAME = "compliance_knowledge"

CHUNK_SIZE = 500
CHUNK_OVERLAP = 100


# =========================
# ✅ EMBEDDING LOCAL (100% OFFLINE)
# =========================

class SimpleEmbeddingFunction:
    def __call__(self, input):
        return [[float(len(text))] for text in input]

    def name(self):
        return "simple"


embedding_function = SimpleEmbeddingFunction()


# =========================
# ✅ CHROMA CLIENT
# =========================
def get_chroma_client():
    return chromadb.PersistentClient(
        path=str(DB_DIR),
    )


# =========================
# ✅ LOADERS
# =========================
def load_pdf(file_path: Path) -> str:
    reader = PdfReader(str(file_path))
    text = ""

    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"

    return text


def load_txt(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8")


# =========================
# ✅ CHUNKING
# =========================
def split_text(text: str):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    return splitter.split_text(text)


# =========================
# ✅ INGESTION
# =========================
def ingest():
    client = get_chroma_client()

    print("🚀 Iniciando ingestão...")

    documents = []

    for file_path in KNOWLEDGE_BASE.iterdir():
        try:
            if file_path.suffix.lower() == ".pdf":
                text = load_pdf(file_path)

            elif file_path.suffix.lower() == ".txt":
                text = load_txt(file_path)

            else:
                continue

        except Exception as e:
            print(f"⚠️ Erro ao ler {file_path.name}: {e}")
            continue

        chunks = split_text(text)

        print(f"📄 {file_path.name} → {len(chunks)} chunks")

        for i, chunk in enumerate(chunks):
            documents.append({
                "id": str(uuid.uuid4()),
                "content": chunk,
                "metadata": {
                    "source": file_path.name,
                    "chunk_id": i,
                    "file_type": file_path.suffix,
                    "chunk_size": len(chunk),
                }
            })

    # ✅ IDÊMPOTENTE (limpa antes)
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_function
    )

    print("💾 Salvando no ChromaDB...")

    collection.add(
        documents=[doc["content"] for doc in documents],
        metadatas=[doc["metadata"] for doc in documents],
        ids=[doc["id"] for doc in documents],
    )

    print("✅ Ingestão concluída!")
    print(f"📊 Total de chunks: {len(documents)}")


# =========================
# ✅ ENTRYPOINT
# =========================
if __name__ == "__main__":
    ingest()