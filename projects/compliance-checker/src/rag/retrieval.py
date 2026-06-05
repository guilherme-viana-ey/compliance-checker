"""
Serviço de recuperação RAG com re-ranking.

Fluxo:
1. Converte a query em embedding
2. Busca os chunks mais próximos no ChromaDB (busca semântica)
3. Aplica re-ranking por relevância (BM25-like score + cobertura de termos)
4. Retorna os chunks ordenados com metadados de fonte
"""

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

import chromadb

# =========================
# ✅ CONFIG
# =========================
BASE_DIR = Path(__file__).resolve().parents[2]
DB_DIR = BASE_DIR / "chroma_db"
COLLECTION_NAME = "compliance_knowledge"

# Número de chunks retornados na busca inicial (antes do re-ranking)
INITIAL_RETRIEVAL_K = 20

# Número de chunks retornados após o re-ranking (enviados ao LLM)
FINAL_TOP_K = 5


# =========================
# ✅ EMBEDDING (deve ser idêntico ao usado na ingestão)
# =========================
class SimpleEmbeddingFunction:
    """
    Função de embedding local (100% offline).
    Compatível com a interface exigida pelo ChromaDB >= 0.5:
      - __call__        → usado na ingestão (embed_documents)
      - embed_documents → vetoriza lista de textos (documentos)
      - embed_query     → vetoriza um único texto (query de busca)
    """

    def __call__(self, input):
        return [[float(len(text))] for text in input]

    def embed_documents(self, input):
        return [[float(len(text))] for text in input]

    def embed_query(self, input):
        # ChromaDB pode passar uma lista ou uma string — tratamos os dois casos
        if isinstance(input, str):
            return [[float(len(input))]]
        return [[float(len(text))] for text in input]

    def name(self):
        return "simple"


embedding_function = SimpleEmbeddingFunction()


# =========================
# ✅ CHUNK RECUPERADO
# =========================
@dataclass
class RetrievedChunk:
    """Representa um chunk recuperado do banco vetorial."""
    content: str
    source_document: str
    chunk_id: int
    file_type: str
    distance: float          # distância vetorial (menor = mais próximo)
    rerank_score: float = 0.0  # score pós re-ranking (maior = mais relevante)


# =========================
# ✅ CHROMA CLIENT
# =========================
def _get_collection():
    client = chromadb.PersistentClient(path=str(DB_DIR))
    return client.get_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_function,
    )


# =========================
# ✅ RE-RANKER
# =========================
def _tokenize(text: str) -> List[str]:
    """Tokenização simples: lowercase + split em não-alfanuméricos."""
    return re.findall(r"[a-záàãâéêíóôõúüçA-ZÁÀÃÂÉÊÍÓÔÕÚÜÇ0-9]+", text.lower())


def _bm25_score(query_tokens: List[str], doc_tokens: List[str], k1: float = 1.5, b: float = 0.75, avg_dl: float = 100.0) -> float:
    """
    Implementação simplificada do BM25.
    Reordena documentos por relevância de termos da query.
    """
    dl = len(doc_tokens)
    freq_map: dict = {}
    for t in doc_tokens:
        freq_map[t] = freq_map.get(t, 0) + 1

    score = 0.0
    for term in query_tokens:
        if term not in freq_map:
            continue
        tf = freq_map[term]
        idf = math.log(1 + 1 / (0.5 + 0.5))  # IDF simplificado (corpus local)
        numerator = tf * (k1 + 1)
        denominator = tf + k1 * (1 - b + b * dl / avg_dl)
        score += idf * (numerator / denominator)

    return score


def _coverage_bonus(query_tokens: List[str], doc_tokens: List[str]) -> float:
    """Bônus proporcional à cobertura de termos únicos da query no documento."""
    doc_set = set(doc_tokens)
    unique_query = set(query_tokens)
    if not unique_query:
        return 0.0
    covered = sum(1 for t in unique_query if t in doc_set)
    return covered / len(unique_query)


def rerank(query: str, chunks: List[RetrievedChunk]) -> List[RetrievedChunk]:
    """
    Re-rankeia os chunks combinando:
    - Score BM25 (relevância de termos)
    - Cobertura de termos da query
    - Proximidade vetorial invertida (1 / (1 + distance))
    """
    query_tokens = _tokenize(query)

    for chunk in chunks:
        doc_tokens = _tokenize(chunk.content)
        bm25 = _bm25_score(query_tokens, doc_tokens)
        coverage = _coverage_bonus(query_tokens, doc_tokens)
        vector_score = 1.0 / (1.0 + chunk.distance)

        # Combinação ponderada dos três sinais
        chunk.rerank_score = (0.5 * bm25) + (0.3 * coverage) + (0.2 * vector_score)

    return sorted(chunks, key=lambda c: c.rerank_score, reverse=True)


# =========================
# ✅ RETRIEVAL PRINCIPAL
# =========================
def retrieve(query: str, top_k: int = FINAL_TOP_K) -> List[RetrievedChunk]:
    """
    Recupera os chunks mais relevantes para a query.

    Args:
        query: Texto da consulta (recomendação de investimento).
        top_k: Número de chunks a retornar após re-ranking.

    Returns:
        Lista de RetrievedChunk ordenados por relevância.
    """
    collection = _get_collection()

    # 1. Busca vetorial inicial (recupera mais do que o necessário)
    results = collection.query(
        query_texts=[query],
        n_results=min(INITIAL_RETRIEVAL_K, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    raw_docs = results["documents"][0]
    raw_meta = results["metadatas"][0]
    raw_dist = results["distances"][0]

    chunks: List[RetrievedChunk] = []
    for doc, meta, dist in zip(raw_docs, raw_meta, raw_dist):
        chunks.append(RetrievedChunk(
            content=doc,
            source_document=meta.get("source", "desconhecido"),
            chunk_id=int(meta.get("chunk_id", -1)),
            file_type=meta.get("file_type", ""),
            distance=float(dist),
        ))

    # 2. Re-ranking
    reranked = rerank(query, chunks)

    # 3. Retorna apenas os top_k melhores
    return reranked[:top_k]


# =========================
# ✅ FORMATAÇÃO DO CONTEXTO PARA O PROMPT
# =========================
def format_context(chunks: List[RetrievedChunk]) -> str:
    """
    Formata os chunks recuperados como bloco de contexto para o LLM.
    Cada trecho é identificado pela fonte e pelo chunk_id.
    """
    lines = []
    for i, chunk in enumerate(chunks, start=1):
        lines.append(
            f"[{i}] Fonte: {chunk.source_document} | Chunk #{chunk.chunk_id}\n"
            f"{chunk.content.strip()}"
        )
    return "\n\n---\n\n".join(lines)