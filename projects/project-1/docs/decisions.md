# Compliance Checker API — Project 1

API REST que atua como um **analista de compliance automatizado**. Recebe uma recomendação de investimento e o perfil de risco do cliente, e devolve uma análise estruturada indicando se a recomendação é adequada, com justificativa e produtos financeiros mencionados.

Construída com **FastAPI**, **Pydantic** e **Azure OpenAI** (via biblioteca `openai` + `instructor` para saída estruturada).

---

## Como funciona

```
Cliente HTTP ──POST /analyze──► FastAPI (src/main.py)
                                     │
                                     ▼
                          compliance_service.analyze_recommendation()
                                     │
                                     ▼
                     AzureModel (src/core/llm_client.py)
                                     │
                                     ▼
                          Azure OpenAI Chat Completions
                                     │
                                     ▼
                  AnalysisResult validado por Pydantic ──► JSON
```

### Fluxo de uma requisição

1. O endpoint `POST /analyze` recebe um `AnalysisRequest` (`text` + `client_profile`) e o FastAPI já valida o payload com Pydantic.
2. `compliance_service.analyze_recommendation()` monta o prompt com a recomendação e o perfil do cliente.
3. **Caminho primário:** chama o modelo via `instructor`, passando `AnalysisResult` como `response_model` — o `instructor` força o LLM a devolver um objeto que respeita o schema.
4. **Caminho de fallback:** se o `instructor` falhar, faz uma chamada padrão pedindo JSON, extrai o primeiro objeto com regex e, em último caso, aplica uma heurística simples baseada na resposta textual.
5. O resultado é serializado como `AnalysisResult` e devolvido em JSON.

### Endpoints

| Método | Rota       | Descrição                                                          |
|--------|------------|--------------------------------------------------------------------|
| GET    | `/`        | Health check. Retorna `{"status": "ok", "service": "..."}`         |
| POST   | `/analyze` | Analisa uma recomendação de investimento contra um perfil de risco |

Documentação interativa (Swagger UI) disponível em `/docs` e ReDoc em `/redoc`.

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
  "reason": "A alocação total em criptomoedas é incompatível com um perfil conservador, que prioriza preservação de capital.",
  "mentioned_products": ["criptomoedas"]
}
```

---

## Estrutura do projeto

```
projects/project-1/
├── .env                       # Credenciais (NÃO versionar)
├── .gitignore
├── Dockerfile
├── README.md
├── requirements.txt
├── test_llm.py                # Script de sanity check do LLM
├── data/                      # Dados de entrada/saída
├── docs/
│   └── decisions.md           # Decisões de arquitetura
├── knowledge_base/            # Base de conhecimento (reservada para o Projeto 2 — RAG)
├── src/
│   ├── __init__.py
│   ├── main.py                # FastAPI app + endpoints
│   ├── api/
│   │   ├── __init__.py
│   │   └── schemas.py         # AnalysisRequest, AnalysisResult
│   ├── core/
│   │   ├── __init__.py
│   │   └── llm_client.py      # Wrapper AzureModel (Azure OpenAI + instructor)
│   ├── services/
│   │   ├── __init__.py
│   │   └── compliance_service.py  # Orquestra prompt → LLM → resultado
│   ├── agents/                # Reservado para o Projeto 3
│   └── rag/                   # Reservado para o Projeto 2
└── tests/
```

---

## Instalação

### Pré-requisitos

- Python 3.11+
- Acesso a um deployment Azure OpenAI (endpoint, chave, deployment name)
- Opcional: Docker, para rodar via container

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

Dependências principais (de `requirements.txt`):

| Pacote               | Para quê                                                        |
|----------------------|-----------------------------------------------------------------|
| `fastapi`            | Framework web e geração automática do OpenAPI                   |
| `uvicorn[standard]`  | Servidor ASGI para executar a app                               |
| `pydantic`           | Validação dos schemas de entrada e saída                        |
| `python-dotenv`      | Carrega as variáveis do `.env`                                  |
| `openai`             | SDK oficial — usado no modo `AzureOpenAI`                       |
| `instructor`         | Força o LLM a devolver objetos Pydantic estruturados            |

### 4. Configurar variáveis de ambiente

Crie um arquivo `.env` na raiz de `projects/project-1/`:

```ini
AZURE_OPENAI_ENDPOINT="https://seu-recurso.openai.azure.com/"
AZURE_OPENAI_KEY="sua-chave-aqui"
AZURE_OPENAI_API_VERSION="2024-06-01"
AZURE_DEPLOYMENT_NAME="seu-deployment-name"
```

> `.env` já deve estar no `.gitignore`. **Nunca** commite credenciais.

### 5. (Opcional) Testar a conexão com o LLM

```bash
python test_llm.py
```

Esse script abre um chat REPL simples contra o Azure OpenAI — útil para validar que as credenciais e o deployment estão corretos antes de subir a API.

---

## Como executar

### Modo desenvolvimento (com hot reload)

A partir de `projects/project-1/`:

```bash
uvicorn src.main:app --reload
```

Acesse:

- API: http://127.0.0.1:8000
- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc

### Modo produção

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

---

## Rodando com Docker

A partir de `projects/project-1/`:

```bash
# Build da imagem
docker build -t compliance-checker-api .

# Run, expondo a porta e passando o .env
docker run --rm -p 8000:8000 --env-file .env compliance-checker-api
```

O `Dockerfile` usa `python:3.11-slim`, instala as dependências e sobe o `uvicorn` na porta `8000`.

---

## Testes

Os testes ficam em `tests/`. Para executar (com `pytest` instalado):

```bash
pip install pytest
pytest
```

---

## Próximos passos

Esta API é a fundação para os próximos projetos do programa:

- **Projeto 2 — RAG:** consumirá `knowledge_base/` e enriquecerá a análise com contexto regulatório.
- **Projeto 3 — Agente autônomo:** usará este serviço como uma das ferramentas disponíveis.

Decisões de arquitetura estão documentadas em [`docs/decisions.md`](docs/decisions.md).