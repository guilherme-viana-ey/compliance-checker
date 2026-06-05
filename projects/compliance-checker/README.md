# Compliance Checker API — Etaoa 2 - RAG Confiável com Re-ranking

API REST que atua como um **analista de compliance automatizado**. Recebe uma recomendação de investimento e o perfil de risco do cliente, e devolve uma análise estruturada indicando se a recomendação é adequada — agora **fundamentada em documentos oficiais** (ANBIMA, CVM) recuperados via RAG.

Construída com **FastAPI**, **Pydantic**, **ChromaDB** e **Azure OpenAI** (via `openai` + `instructor`).

---

## O que mudou em relação ao Projeto 1

No Projeto 1, as regras de compliance estavam **congeladas no prompt**. Se uma política mudasse, era necessário reescrever e reimplantar o código. A análise também não era auditável — não era possível apontar qual cláusula embasou cada decisão.

No Projeto 2, a API se torna um **Policy-Grounded RAG**:

| | Projeto 1 | Projeto 2 |
|---|---|---|
| **Fonte das regras** | Prompt fixo no código | Documentos oficiais (PDF/TXT) |
| **Auditabilidade** | Nenhuma | Fonte + chunk_id em cada resposta |
| **Atualização de políticas** | Requer redeploy | Rodar `ingestion.py` novamente |
| **Qualidade do contexto** | N/A | Re-ranking BM25 + vetorial |
| **Schema de resposta** | 3 campos | 4 campos + lista de fontes |

---

## Como funciona

```
                    ┌─────────────────────────────────┐
                    │  INGESTÃO (offline, sob demanda) │
                    │                                  │
                    │  knowledge_base/*.pdf/.txt        │
                    │         ↓ chunking               │
                    │  ChromaDB (chroma_db/)           │
                    └─────────────────────────────────┘
                                    │
                                    ▼ (consulta em tempo real)

Cliente HTTP ──POST /analyze──► FastAPI (src/main.py)
                                     │
                                     ▼
                     compliance_service.analyze_recommendation()
                                     │
                          ┌──────────┴──────────┐
                          ▼                     ▼
                    retrieval.retrieve()    AzureModel
                          │                     ▲
                    Busca vetorial              │
                    ChromaDB top-20            prompt enriquecido
                          │                   (Strict Grounding)
                    Re-ranking BM25 ──────────►│
                    + cobertura                │
                    + score vetorial           │
                          │                     │
                          └──────────┬──────────┘
                                     ▼
                    AnalysisResult + sources (Pydantic) ──► JSON
```

### Fluxo de uma requisição

1. O endpoint `POST /analyze` recebe um `AnalysisRequest` (`text` + `client_profile`).
2. `compliance_service` chama `retrieval.retrieve()` com o texto da recomendação como query.
3. O serviço de recuperação busca os **20 chunks mais próximos** no ChromaDB.
4. O **re-ranker** reordena os chunks combinando BM25, cobertura de termos e score vetorial — retorna os top-5.
5. O serviço monta um prompt de **Strict Grounding** com o contexto recuperado.
6. O LLM é chamado via `instructor` (com fallback em três camadas) e retorna a análise.
7. A resposta inclui o resultado da análise **e as fontes** usadas (documento + chunk_id).

### Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/` | Health check. Retorna `{"status": "ok"}` |
| POST | `/analyze` | Analisa uma recomendação com contexto RAG |

Documentação interativa disponível em `/docs` (Swagger UI) e `/redoc`.

#### Exemplo de request

```bash
curl -X POST http://127.0.0.1:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Recomendo alocar 100% do patrimônio em criptomoedas.",
    "client_profile": "conservador"
  }'
```

#### Exemplo de response

```json
{
  "is_compliant": false,
  "reason": "A recomendação viola o Art. 12 da Resolução CVM 30, que exige adequação do produto ao perfil do investidor. Criptomoedas são ativos de alto risco, incompatíveis com perfil conservador.",
  "mentioned_products": ["criptomoedas"],
  "sources": [
    {
      "source_document": "resol_030_cvm.pdf",
      "source_chunk_id": 12,
      "relevance_score": 0.8734,
      "excerpt": "O distribuidor deve verificar a adequação do produto ao perfil do investidor antes de qualquer recomendação..."
    },
    {
      "source_document": "politica_adequacao_investimento_v1.2.txt",
      "source_chunk_id": 3,
      "relevance_score": 0.7210,
      "excerpt": "Investidores conservadores devem ter exposição máxima de 10% em ativos de risco..."
    }
  ]
}
```

---

## Estrutura do projeto

```
projects/project-1/
├── .env                            # Credenciais (NÃO versionar)
├── .gitignore
├── Dockerfile
├── README.md
├── requirements.txt
├── test_llm.py                     # Script de sanity check do LLM
├── chroma_db/                      # Banco vetorial gerado pela ingestão
├── data/
├── docs/
│   └── architecture.md             # Diagrama do fluxo RAG completo
├── knowledge_base/                 # Documentos oficiais
│   ├── anbima_codigo_distribuicao_produtos_Investimento.pdf
│   ├── resol_030_cvm.pdf
│   ├── politica_adequacao_investimento_v1.2.txt
│   ├── politica_investimento_agressivo_v1.0.txt
│   ├── manual_comunicacao_cliente_v1.0.txt
│   └── analise_de_perfil_do_investidor.txt
├── notebooks/
│   └── rag_evaluation.ipynb        # Análise before/after re-ranking
└── src/
    ├── __init__.py
    ├── main.py                     # FastAPI app + endpoints
    ├── api/
    │   ├── __init__.py
    │   └── schemas.py              # AnalysisRequest, AnalysisResult, SourceReference
    ├── core/
    │   ├── __init__.py
    │   └── llm_client.py           # Wrapper AzureModel (imutável)
    ├── rag/
    │   ├── __init__.py
    │   ├── ingestion.py            # Pipeline de ingestão (executável)
    │   └── retrieval.py            # Busca vetorial + re-ranking
    ├── services/
    │   ├── __init__.py
    │   └── compliance_service.py   # Orquestrador RAG
    └── agents/                     # Reservado para o Projeto 3
```

---

## Instalação

### Pré-requisitos

- Python 3.11+
- Acesso a um deployment Azure OpenAI (endpoint, chave, deployment name)
- Opcional: Docker

### 1. Clonar e entrar na pasta

```bash
git clone https://github.com/GuilhermeVDAP/development-program-ai_engineer.git
cd development-program-ai_engineer/projects/project-1
```

### 2. Criar e ativar o ambiente virtual

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Instalar dependências

```bash
pip install -r requirements.txt
```

Dependências principais:

| Pacote | Para quê |
|--------|----------|
| `fastapi` | Framework web e geração automática do OpenAPI |
| `uvicorn[standard]` | Servidor ASGI |
| `pydantic` | Validação dos schemas de entrada e saída |
| `python-dotenv` | Carrega variáveis do `.env` |
| `openai` | SDK oficial Azure OpenAI |
| `instructor` | Força o LLM a devolver objetos Pydantic estruturados |
| `chromadb` | Banco de dados vetorial local |
| `langchain-text-splitters` | Chunking dos documentos |
| `pypdf` | Leitura de arquivos PDF |
| `pandas` | Análise de dados no notebook de avaliação |

### 4. Configurar variáveis de ambiente

Crie um arquivo `.env` na raiz de `projects/project-1/`:

```ini
AZURE_OPENAI_ENDPOINT="https://seu-recurso.openai.azure.com/"
AZURE_OPENAI_KEY="sua-chave-aqui"
AZURE_OPENAI_API_VERSION="2024-06-01"
AZURE_DEPLOYMENT_NAME="seu-deployment-name"
```

> `.env` já está no `.gitignore`. **Nunca** commite credenciais.

---

## Como executar

### Passo 1 — Rodar a ingestão (necessário antes de subir a API)

```bash
python src/rag/ingestion.py
```

Saída esperada:
```
🚀 Iniciando ingestão...
📄 anbima_codigo_distribuicao_produtos_Investimento.pdf → 301 chunks
📄 resol_030_cvm.pdf → 50 chunks
📄 politica_adequacao_investimento_v1.2.txt → 6 chunks
...
✅ Ingestão concluída!
📊 Total de chunks: 369
```

A ingestão é **idempotente**: pode ser rodada múltiplas vezes sem problemas. Sempre recria a base do zero, garantindo que mudanças nos documentos sejam refletidas.

### Passo 2 — Subir a API

```bash
uvicorn src.main:app --reload
```

Acesse:
- API: http://127.0.0.1:8000
- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc

### Passo 3 — (Opcional) Rodar o notebook de avaliação

```bash
pip install jupyter
jupyter notebook notebooks/rag_evaluation.ipynb
```

O notebook compara a qualidade da recuperação antes e depois do re-ranking para 3 queries de teste.

---

## Rodando com Docker

```bash
# Build da imagem
docker build -t compliance-checker-api .

# Run passando o .env
docker run --rm -p 8000:8000 --env-file .env compliance-checker-api
```

> **Atenção:** ao usar Docker, rode a ingestão antes do build ou monte o volume do `chroma_db/` no container.

---

## Componentes novos (Projeto 2)

### `src/rag/ingestion.py` — Pipeline de Ingestão

Lê todos os arquivos da `knowledge_base/`, aplica chunking semântico com sobreposição e armazena os vetores no ChromaDB. Executável diretamente via `python src/rag/ingestion.py`.

### `src/rag/retrieval.py` — Serviço de Recuperação com Re-ranking

Dado um texto de query, busca os 20 chunks mais próximos no ChromaDB e aplica re-ranking combinando três sinais:

```
rerank_score = 0.5 × BM25
             + 0.3 × cobertura de termos
             + 0.2 × (1 / (1 + distância vetorial))
```

Retorna os top-5 chunks com metadados de fonte.

### `src/api/schemas.py` — Schema Atualizado

Adicionado o modelo `SourceReference` e o campo `sources` em `AnalysisResult`:

```python
class SourceReference(BaseModel):
    source_document: str   # nome do arquivo de origem
    source_chunk_id: int   # índice do chunk no documento
    relevance_score: float # score pós re-ranking
    excerpt: str           # preview do trecho usado
```

### `src/services/compliance_service.py` — Orquestrador RAG

Refatorado para orquestrar o fluxo completo: recuperação → re-ranking → prompt enriquecido → LLM → resposta com fontes. Usa **Strict Grounding**: o LLM é instruído a basear a análise exclusivamente no contexto recuperado.

---

## Próximos passos

- **Projeto 3 — Agente autônomo:** usará este serviço como uma das ferramentas disponíveis no `src/agents/`.

Decisões de arquitetura estão documentadas em [`docs/architecture.md`](docs/architecture.md).
