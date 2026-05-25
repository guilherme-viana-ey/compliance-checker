"""
Pipeline de ingestão RAG:
- lê PDFs da knowledge_base
- faz chunking
- gera embeddings
- armazena no ChromaDB

Idempotente: pode rodar várias vezes sem duplicar dados
"""

import os
import uuid
from pathlib import Path

import chromadb
from chromadb.config import Settings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from pypdf import PdfReader

# ✅ CONFIG
BASE_DIR = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE = BASE_DIR / "knowledge_base"
DB_DIR = BASE_DIR / "chroma_db"

CHUNK_SIZE = 500
CHUNK_OVERLAP = 100


# ✅ CLIENTE CHROMA
def get_chroma_collection():
    client = chromadb.Client(
        Settings(persist_directory=str(DB_DIR))
    )

    collection = client.get_or_create_collection(
        name="compliance_knowledge"
    )

    return client, collection


# ✅ LEITURA DE PDF
def load_pdf(file_path: Path) -> str:
    reader = PdfReader(str(file_path))
    text = ""

    for page in reader.pages:
        text += page.extract_text() + "\n"

    return text


# ✅ LOAD DE TXT (caso tenha perfil de risco)
def load_txt(file_path: Path) -> str:
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


# ✅ SPLIT EM CHUNKS
def split_text(text: str):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    return splitter.split_text(text)


# ✅ INGESTÃO PRINCIPAL
def ingest():
    client, collection = get_chroma_collection()

    print("🚀 Iniciando ingestão...")

    documents = []

    for file_path in KNOWLEDGE_BASE.iterdir():

        if file_path.suffix.lower() == ".pdf":
            text = load_pdf(file_path)

        elif file_path.suffix.lower() == ".txt":
            text = load_txt(file_path)

        else:
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
                }
            })

    # ✅ evitar duplicação (simples estratégia: limpar antes)
    collection.delete(where={})

    print("💾 Salvando no ChromaDB...")

    collection.add(
        documents=[doc["content"] for doc in documents],
        metadatas=[doc["metadata"] for doc in documents],
        ids=[doc["id"] for doc in documents],
    )

    client.persist()

    print("✅ Ingestão concluída!")
    print(f"Total de chunks: {len(documents)}")


# ✅ ENTRYPOINT
if __name__ == "__main__":
    ingest()