# Compliance Checker

Sistema autônomo de análise de conformidade para o mercado financeiro brasileiro. Analisa recomendações de investimento contra documentos regulatórios oficiais (ANBIMA, CVM) e toma decisões automatizadas sobre aprovação ou rejeição, com rastreabilidade completa de cada decisão.

> Repositório: [github.com/guilherme-viana-ey/compliance-checker](https://github.com/guilherme-viana-ey/compliance-checker)

---

## Sumário

- [Visão Geral](#visão-geral)
- [Evolução do Sistema](#evolução-do-sistema)
- [Arquitetura](#arquitetura)
- [Tecnologias e Bibliotecas](#tecnologias-e-bibliotecas)
- [Estrutura de Arquivos](#estrutura-de-arquivos)
- [Como Executar](#como-executar)
- [Indicador de Automação](#indicador-de-automação)
- [Base de Conhecimento](#base-de-conhecimento)
- [Decisões Arquiteturais](#decisões-arquiteturais)

---

## Visão Geral

O sistema resolve um problema real do dia a dia de equipes de compliance em instituições financeiras: analisar se uma recomendação de investimento está adequada ao perfil de risco do cliente, com base nas normas da CVM e ANBIMA.

**Antes do sistema:**
- Analista pega o documento de recomendação
- Consulta manualmente os documentos regulatórios
- Decide se está conforme ou não
- Registra a decisão e arquiva o documento
- Tempo médio: 15 minutos por documento

**Depois do sistema:**
- Documento chega na pasta `data/input/`
- Agente detecta, analisa e decide automaticamente
- Arquivo é movido para `approved/` ou `rejected_for_review/`
- Alerta criado automaticamente para casos rejeitados
- Tempo médio: 3-5 segundos por documento

---

## Evolução do Sistema

O sistema foi construído em três etapas progressivas, cada uma adicionando uma camada de inteligência e autonomia.

---

### Etapa 1 — API Base

**O problema:** criar uma API que analisa recomendações de investimento usando um LLM.

**O que foi construído:**
- Endpoint `POST /analyze` que recebe texto + perfil do cliente
- Integração com Azure OpenAI via `instructor` para saída estruturada
- Schema Pydantic com `is_compliant`, `reason` e `mentioned_products`
- Fallback em três camadas para garantir resposta mesmo em falhas

**Limitação:** as regras de compliance estavam congeladas no prompt. Se uma norma mudasse, era necessário reescrever e reimplantar o código. A análise não era auditável.

```
Cliente HTTP → POST /analyze → FastAPI → compliance_service → Azure OpenAI → AnalysisResult
```

---

### Etapa 2 — RAG com Re-ranking

**O problema:** a análise precisa ser baseada em documentos oficiais reais, não em conhecimento genérico do LLM.

**O que foi construído:**
- Pipeline de ingestão que lê PDFs e TXTs, aplica chunking e armazena no ChromaDB
- Serviço de recuperação com busca vetorial + re-ranking BM25
- Prompt de Strict Grounding — LLM analisa APENAS com base nos chunks recuperados
- Schema atualizado com campo `sources` — cada resposta aponta para as cláusulas usadas

**Fórmula do re-ranking:**
```
rerank_score = 0.5 × BM25 + 0.3 × cobertura de termos + 0.2 × score vetorial
```

**Ganho:** análise auditável. É possível apontar exatamente qual cláusula, de qual documento, embasou cada decisão. Atualizar as políticas é só rodar `ingestion.py` novamente — nenhum código precisa ser alterado.

```
POST /analyze
    ↓
retrieval.py → ChromaDB (top-20) → re-ranking → top-5 chunks
    ↓
prompt enriquecido (strict grounding)
    ↓
Azure OpenAI → AnalysisResult + sources
```

---

### Etapa 3 — Agente Autônomo

**O problema:** o processo ainda dependia de intervenção humana para acionar a API.

**O que foi construído:**
- Agente LangGraph com grafo de estados explícito
- Watcher que monitora `data/input/` em tempo real
- Ferramentas (tools) para ler, analisar, mover arquivos e criar alertas
- Dois modos: batch (processa lote) e watch (daemon em tempo real)
- Logs estruturados em texto e JSON para rastreabilidade completa
- Indicador de automação calculado automaticamente

**Grafo de estados:**
```
START → read_document → analyze_compliance → [approve | reject] → END
```

**Ganho:** o sistema passou de reativo (espera ser chamado) para autônomo (age sozinho). A equipe de compliance só é acionada para os casos que realmente exigem atenção humana.

---

## Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│  INGESTÃO (offline — roda sob demanda)                       │
│                                                              │
│  knowledge_base/*.pdf/*.txt                                  │
│         ↓ pypdf / read_text                                  │
│  RecursiveCharacterTextSplitter (chunk=500, overlap=100)     │
│         ↓                                                    │
│  SimpleEmbeddingFunction                                     │
│         ↓                                                    │
│  ChromaDB PersistentClient → chroma_db/                      │
└─────────────────────────────────────────────────────────────┘
                         ↑ consulta
┌─────────────────────────────────────────────────────────────┐
│  FLUXO API (online — por requisição HTTP)                    │
│                                                              │
│  POST /analyze {text, client_profile}                        │
│         ↓                                                    │
│  compliance_service.analyze_recommendation()                 │
│         ↓                                                    │
│  retrieval.retrieve(query) → ChromaDB top-20                 │
│         ↓                                                    │
│  rerank() → BM25 + cobertura + score vetorial → top-5        │
│         ↓                                                    │
│  _build_rag_prompt() → strict grounding                      │
│         ↓                                                    │
│  AzureModel (instructor / invoke fallback)                   │
│         ↓                                                    │
│  AnalysisResult {is_compliant, reason, products, sources}    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  FLUXO AGENTE (autônomo — por evento de arquivo)             │
│                                                              │
│  data/input/ ← novo arquivo                                  │
│         ↓                                                    │
│  watcher.py (watchdog inotify/FSEvents)                      │
│         ↓                                                    │
│  compliance_agent.py (LangGraph)                             │
│    ├── node: read_document  → tool_read_document()           │
│    ├── node: analyze        → tool_analyze_compliance()      │
│    ├── route: is_compliant? → approve | reject               │
│    ├── node: approve        → tool_move_file("approved")     │
│    └── node: reject         → tool_move_file("rejected")     │
│                               tool_create_alert()            │
│         ↓                                                    │
│  data/output/approved/                                       │
│  data/output/rejected_for_review/                            │
│  data/logs/alerts.log                                        │
│  data/logs/execution_*.json                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## Tecnologias e Bibliotecas

### Backend e API

| Biblioteca | Para quê |
|---|---|
| `fastapi` | Framework web — gera Swagger automaticamente a partir dos schemas Pydantic |
| `uvicorn[standard]` | Servidor ASGI para executar a aplicação |
| `pydantic` | Validação de entrada, saída e contrato do LLM — fonte única de verdade |
| `python-dotenv` | Carrega credenciais do `.env` |

**Por que FastAPI e não Flask?** FastAPI valida request e response via Pydantic e gera documentação interativa automaticamente. Flask exigiria validação manual e documentação separada.

---

### LLM e Saída Estruturada

| Biblioteca | Para quê |
|---|---|
| `openai` | SDK oficial do Azure OpenAI |
| `instructor` | Força o LLM a retornar objetos Pydantic estruturados via function calling — elimina o ciclo de parse manual de JSON |

---

### RAG e Base de Conhecimento

| Biblioteca | Para quê |
|---|---|
| `chromadb` | Banco vetorial local com persistência automática e suporte a metadados nativos |
| `langchain-text-splitters` | `RecursiveCharacterTextSplitter` — chunking semântico que respeita parágrafos e frases |
| `pypdf` | Extração de texto de PDFs digitais sem dependências nativas |

**Por que ChromaDB e não FAISS?** ChromaDB funciona como biblioteca Python pura, persiste automaticamente e suporta metadados (`source`, `chunk_id`) nativamente. FAISS é mais performático para bases grandes mas não tem essas funcionalidades.

---

### Agente Autônomo

| Biblioteca | Para quê |
|---|---|
| `langgraph` | Modela o fluxo do agente como grafo de estados explícito com transições declarativas |
| `watchdog` | Monitora diretório usando APIs nativas do SO (inotify/FSEvents) — sem polling |

**Por que LangGraph e não um loop manual?** LangGraph torna o fluxo visível, auditável e extensível. O estado centralizado (`ComplianceState`) registra tudo que aconteceu em cada etapa.

---

## Estrutura de Arquivos

```
compliance-checker/
│
├── README.md                         # Este arquivo
│
└── projects/
    └── compliance-checker/
        │
        ├── .env                          # Credenciais Azure OpenAI (não versionar)
        ├── .gitignore
        ├── Dockerfile
        ├── requirements.txt
        ├── test_llm.py                   # Sanity check da conexão com o LLM
        ├── test_agent.py                 # Sanity check das tools do agente
        │
        ├── data/
        │   ├── input/                    # Pasta monitorada pelo agente
        │   ├── output/
        │   │   ├── approved/             # Documentos aprovados automaticamente
        │   │   └── rejected_for_review/  # Documentos para revisão humana
        │   └── logs/
        │       ├── alerts.log            # Alertas de não-conformidade
        │       └── execution_*.json      # Log completo de cada lote
        │
        ├── docs/
        │   ├── architecture.md           # Diagrama do sistema RAG
        │   ├── decisions.md              # Decisões arquiteturais
        │   ├── DEVELOPER_GUIDE.md
        │   └── SDD.md
        │
        ├── knowledge_base/               # Documentos regulatórios oficiais
        │   ├── anbima_codigo_distribuicao_produtos_Investimento.pdf
        │   ├── resol_030_cvm.pdf
        │   ├── politica_adequacao_investimento_v1.2.txt
        │   ├── politica_investimento_agressivo_v1.0.txt
        │   ├── manual_comunicacao_cliente_v1.0.txt
        │   └── analise_de_perfil_do_investidor.txt
        │
        ├── notebooks/
        │   └── rag_evaluation.ipynb      # Análise before/after re-ranking
        │
        ├── tests/
        │
        └── src/
            ├── main.py                   # FastAPI app — ponto de entrada da API
            │
            ├── api/
            │   └── schemas.py            # AnalysisRequest, AnalysisResult, SourceReference
            │
            ├── core/
            │   └── llm_client.py         # AzureModel — wrapper Azure OpenAI + instructor
            │
            ├── rag/
            │   ├── ingestion.py          # Pipeline de ingestão (executável)
            │   └── retrieval.py          # Busca vetorial + re-ranking BM25
            │
            ├── services/
            │   └── compliance_service.py # Orquestrador RAG — conecta retrieval + LLM
            │
            └── agents/
                ├── tools.py              # Ações atômicas do agente
                ├── compliance_agent.py   # Grafo LangGraph + nós
                ├── watcher.py            # Monitoramento de data/input/
                └── runner.py             # Ponto de entrada — batch ou watch
```

---

## Como Executar

### Pré-requisitos

- Python 3.11+
- Acesso a um deployment Azure OpenAI

### 1. Clonar o repositório

```bash
git clone https://github.com/guilherme-viana-ey/compliance-checker.git
cd compliance-checker/projects/compliance-checker
```

### 2. Criar e ativar o ambiente virtual

```bash
# Windows
python -m venv .venv
.venv\Scripts\Activate.ps1

# macOS / Linux
python -m venv .venv
source .venv/bin/activate
```

### 3. Instalar dependências

```bash
pip install -r requirements.txt
pip install langgraph watchdog
```

### 4. Configurar credenciais

Crie um arquivo `.env` na raiz do projeto:

```ini
AZURE_OPENAI_ENDPOINT="https://seu-recurso.openai.azure.com/"
AZURE_OPENAI_KEY="sua-chave-aqui"
AZURE_OPENAI_API_VERSION="2024-06-01"
AZURE_DEPLOYMENT_NAME="seu-deployment-name"
```

### 5. Rodar a ingestão

Precisa ser executado uma vez antes de qualquer outra coisa. Popula o ChromaDB com os chunks dos documentos regulatórios:

```bash
python src/rag/ingestion.py
```

Saída esperada:
```
🚀 Iniciando ingestão...
📄 anbima_codigo_distribuicao_produtos_Investimento.pdf → 301 chunks
📄 resol_030_cvm.pdf → 50 chunks
📄 politica_adequacao_investimento_v1.2.txt → 6 chunks
✅ Ingestão concluída!
📊 Total de chunks: 369
```

### 6. Usar a API

```bash
uvicorn src.main:app --reload
```

Acesse `http://127.0.0.1:8000/docs` e teste o endpoint `POST /analyze`:

```json
{
  "text": "Recomendo alocar 100% do patrimônio em criptomoedas.",
  "client_profile": "conservador"
}
```

Resposta esperada:
```json
{
  "is_compliant": false,
  "reason": "A recomendação viola o Art. 12 da Resolução CVM 30...",
  "mentioned_products": ["criptomoedas"],
  "sources": [
    {
      "source_document": "resol_030_cvm.pdf",
      "source_chunk_id": 12,
      "relevance_score": 0.8734,
      "excerpt": "O distribuidor deve verificar a adequação..."
    }
  ]
}
```

### 7. Usar o agente

**Formato dos arquivos de entrada** — salve em `data/input/`:
```
PERFIL: conservador
RECOMENDAÇÃO: Recomendo alocar 80% em Tesouro Direto e 20% em CDB.
```

**Modo batch** — processa todos os arquivos existentes e exibe relatório:
```bash
python -m src.agents.runner --mode batch
```

**Modo watch** — monitora em tempo real:
```bash
python -m src.agents.runner --mode watch
```

### 8. Rodar API e agente simultaneamente

```bash
# Terminal 1
uvicorn src.main:app --reload

# Terminal 2
python -m src.agents.runner --mode watch
```

---

## Indicador de Automação

Executado com 4 documentos de teste (2 conformes, 2 não-conformes):

| Métrica | Valor |
|---|---|
| Total de documentos processados | 4 |
| Aprovados automaticamente | 2 |
| Rejeitados com alerta criado | 2 |
| Erros críticos (intervenção manual) | 0 |
| **Taxa de automação** | **100%** |
| Tempo médio por análise | ~4 segundos |

**Ganho de eficiência:**

| | Antes (manual) | Depois (agente) |
|---|---|---|
| Tempo por documento | 15 minutos | ~4 segundos |
| 4 documentos | 60 minutos | ~16 segundos |
| 100 documentos/semana | 25 horas | ~7 minutos |
| **Redução de trabalho** | — | **99,5%** |

> O analista humano continua sendo acionado apenas para casos com erro crítico ou que exigem julgamento subjetivo. Casos rejeitados são automáticos — o agente já moveu o arquivo e criou o alerta pré-triado.

---

## Base de Conhecimento

O sistema é alimentado com documentos oficiais do mercado financeiro brasileiro:

| Documento | Tipo | Conteúdo |
|---|---|---|
| `anbima_codigo_distribuicao_produtos_Investimento.pdf` | PDF | Regras e melhores práticas para distribuição de produtos de investimento |
| `resol_030_cvm.pdf` | PDF | Resolução CVM 30 — arcabouço legal de suitability |
| `politica_adequacao_investimento_v1.2.txt` | TXT | Política interna de adequação de investimentos |
| `politica_investimento_agressivo_v1.0.txt` | TXT | Política para perfil arrojado |
| `manual_comunicacao_cliente_v1.0.txt` | TXT | Manual de comunicação com o cliente |
| `analise_de_perfil_do_investidor.txt` | TXT | Definição das categorias de perfil de risco |

Para atualizar a base de conhecimento, substitua ou adicione arquivos em `knowledge_base/` e rode:

```bash
python src/rag/ingestion.py
```

Nenhum código precisa ser alterado.

---

## Decisões Arquiteturais

### Separação em camadas

Cada módulo só conhece a camada imediatamente abaixo:

```
main.py                (API — recebe HTTP)
    ↓
compliance_service.py  (orquestração — conecta peças)
    ↓
retrieval.py + llm_client.py  (infraestrutura)
    ↓
ChromaDB + Azure OpenAI  (serviços externos)
```

Trocar o ChromaDB por Pinecone afeta apenas `retrieval.py`. Trocar Azure OpenAI por outro provedor afeta apenas `llm_client.py`.

### Strict Grounding

O LLM é explicitamente instruído a basear sua análise exclusivamente no contexto recuperado. Isso é crítico em compliance porque garante que cada decisão pode ser auditada contra um trecho específico de um documento oficial, e evita que o modelo use versões desatualizadas das normas aprendidas durante o treinamento.

### Fail-safe no agente

Em caso de qualquer erro (arquivo inválido, falha na API, timeout), o agente sempre rejeita o documento e cria um alerta. Nunca aprova erroneamente. É mais seguro para compliance rejeitar um caso ambíguo e escalar para revisão humana.

### Idempotência na ingestão

O pipeline apaga e recria a coleção a cada execução. Isso garante que a base esteja sempre consistente com os arquivos em `knowledge_base/`, sem risco de chunks duplicados ou desatualizados.

---
