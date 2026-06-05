# Arquitetura do Sistema RAG — Compliance Checker API

## Visão Geral

O sistema é composto por dois fluxos principais:

1. **Pipeline de Ingestão** (offline, executado uma vez ou sob demanda)
2. **Fluxo de Análise RAG** (online, a cada requisição ao endpoint `/analyze`)

---

## Diagrama de Fluxo Completo

```mermaid
flowchart TD
    subgraph INGESTÃO ["📥 Pipeline de Ingestão (src/rag/ingestion.py)"]
        A1[knowledge_base/\n*.pdf  *.txt] -->|load_pdf / load_txt| A2[Texto bruto]
        A2 -->|RecursiveCharacterTextSplitter\nchunk=500 overlap=100| A3[Chunks de texto]
        A3 -->|SimpleEmbeddingFunction| A4[Vetores de embedding]
        A4 -->|PersistentClient.add| A5[(ChromaDB\nchroma_db/)]
    end

    subgraph API ["🌐 API FastAPI (src/main.py)"]
        B1[POST /analyze\nAnalysisRequest\ntext + client_profile]
    end

    subgraph RAG ["🔍 Fluxo RAG (src/services/compliance_service.py)"]
        B1 --> C1[retrieve query\nsrc/rag/retrieval.py]

        subgraph RETRIEVAL ["Recuperação + Re-ranking"]
            C1 -->|query_texts| C2[Busca Vetorial\nChromaDB top-20]
            C2 --> C3[Re-ranking\nBM25 + cobertura\n+ score vetorial]
            C3 -->|top-5 chunks| C4[Chunks ordenados\ncom metadados]
        end

        C4 --> D1[format_context\nmonta bloco de contexto]
        D1 --> D2[_build_rag_prompt\nStrict Grounding:\ncontexto + query + perfil]
        D2 --> D3[AzureModel\ninstructor / invoke]
        D3 --> D4[AnalysisResult\nis_compliant + reason\n+ mentioned_products\n+ sources]
    end

    A5 -.->|consulta| C2
    D4 --> E1[Resposta JSON\nao cliente]
```

---

## Componentes

### `src/rag/ingestion.py` — Pipeline de Ingestão

| Etapa | Detalhe |
|---|---|
| **Leitura** | `PdfReader` (pypdf) para PDFs; `Path.read_text` para TXT |
| **Chunking** | `RecursiveCharacterTextSplitter` — tamanho 500, overlap 100 |
| **Embedding** | `SimpleEmbeddingFunction` (offline, sem dependência externa) |
| **Armazenamento** | `chromadb.PersistentClient` — coleção `compliance_knowledge` |
| **Idempotência** | `delete_collection` antes de recriar — garante base sempre atualizada |

### `src/rag/retrieval.py` — Serviço de Recuperação

| Etapa | Detalhe |
|---|---|
| **Busca vetorial** | `collection.query` — retorna os 20 chunks mais próximos |
| **Re-ranking** | Score combinado: `0.5×BM25 + 0.3×cobertura + 0.2×score_vetorial` |
| **Saída** | Top-5 `RetrievedChunk` ordenados por `rerank_score` |

#### Fórmula de Re-ranking

```
rerank_score = 0.5 × BM25(query, chunk)
             + 0.3 × cobertura_de_termos(query, chunk)
             + 0.2 × (1 / (1 + distância_vetorial))
```

- **BM25**: penaliza documentos muito longos e premia frequência de termos da query
- **Cobertura**: fração de termos únicos da query presentes no chunk
- **Score vetorial**: proximidade semântica calculada na busca inicial

### `src/api/schemas.py` — Contratos da API

```
AnalysisRequest          AnalysisResult
─────────────────        ──────────────────────────────────
text            →        is_compliant: bool
client_profile  →        reason: str
                         mentioned_products: List[str]
                         sources: List[SourceReference]
                                  ├── source_document
                                  ├── source_chunk_id
                                  ├── relevance_score
                                  └── excerpt
```

### `src/services/compliance_service.py` — Orquestrador RAG

1. Chama `retrieve(query)` → obtém chunks re-rankeados
2. Chama `format_context(chunks)` → formata bloco de contexto
3. Constrói prompt com **Strict Grounding** (LLM instruído a usar APENAS o contexto)
4. Chama `AzureModel` via `instructor` (saída estruturada) ou `invoke` (fallback)
5. Mescla resultado do LLM com `sources` vindos do retrieval

---

## Fluxo de Dados — Diagrama de Sequência

```mermaid
sequenceDiagram
    actor Cliente
    participant API as FastAPI /analyze
    participant SVC as compliance_service
    participant RET as retrieval
    participant DB  as ChromaDB
    participant LLM as Azure OpenAI

    Cliente->>API: POST /analyze {text, client_profile}
    API->>SVC: analyze_recommendation(request)
    SVC->>RET: retrieve(query=text)
    RET->>DB: collection.query(top-20)
    DB-->>RET: docs + metadatas + distances
    RET->>RET: rerank(BM25 + coverage + vector)
    RET-->>SVC: top-5 RetrievedChunk
    SVC->>SVC: format_context(chunks)
    SVC->>SVC: _build_rag_prompt(context, request)
    SVC->>LLM: chat.completions.create(prompt)
    LLM-->>SVC: {is_compliant, reason, mentioned_products}
    SVC-->>API: AnalysisResult + sources
    API-->>Cliente: JSON response
```

---

## Estrutura de Arquivos Relevantes

```
project-1/
├── knowledge_base/          # Documentos oficiais (PDFs + TXTs)
├── chroma_db/               # Banco vetorial persistido
├── src/
│   ├── main.py              # Ponto de entrada FastAPI
│   ├── api/
│   │   └── schemas.py       # AnalysisRequest, AnalysisResult, SourceReference
│   ├── core/
│   │   └── llm_client.py    # AzureModel (wrapper Azure OpenAI)
│   ├── rag/
│   │   ├── ingestion.py     # Pipeline de ingestão (offline)
│   │   └── retrieval.py     # Busca vetorial + re-ranking
│   └── services/
│       └── compliance_service.py  # Orquestrador RAG
└── notebooks/
    └── rag_evaluation.ipynb # Análise before/after re-ranking
```
