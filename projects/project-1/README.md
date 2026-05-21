# Projeto 1 — Compliance Checker API

API REST que simula um analista de compliance de serviços financeiros.
Recebe uma recomendação de investimento e o perfil de risco do cliente
e devolve uma análise estruturada indicando se a recomendação é
adequada, com a justificativa e os produtos citados.

A análise é feita por um LLM (Azure OpenAI) e a resposta é validada
contra um schema Pydantic usando a biblioteca `instructor`.

---

## Cenário de negócio

Analistas de compliance gastam um tempo considerável revisando
manualmente comunicações para garantir adequação ao perfil de risco do
cliente — processo lento, caro e sujeito a falhas humanas.

Esta API é a fundação de uma solução automatizada: um serviço
especialista capaz de fazer a triagem inicial de uma recomendação,
liberando o analista humano para focar nos casos realmente sensíveis.

---

## Arquitetura em alto nível

```
┌──────────────────┐    POST /analyze    ┌──────────────────────┐
│  Cliente HTTP    │ ──────────────────▶ │  FastAPI (main.py)   │
│  (Swagger/curl)  │                     │   - valida payload   │
└──────────────────┘                     │   - chama service    │
                                         └──────────┬───────────┘
                                                    │
                                                    ▼
                                  ┌──────────────────────────────┐
                                  │  compliance_service          │
                                  │  - monta prompt              │
                                  │  - chama LLM (instructor)    │
                                  │  - fallback JSON manual      │
                                  └──────────┬───────────────────┘
                                             │
                                             ▼
                                  ┌──────────────────────────────┐
                                  │  AzureModel (llm_client)     │
                                  │  - openai + instructor       │
                                  │  - credenciais via .env      │
                                  └──────────┬───────────────────┘
                                             │
                                             ▼
                                       Azure OpenAI
```

Separação de responsabilidades:

- **`src/main.py`** — camada HTTP. Só conhece schemas e chama o service.
- **`src/api/schemas.py`** — contratos de entrada e saída (Pydantic).
- **`src/services/compliance_service.py`** — regra de negócio. Monta o
  prompt e orquestra a chamada ao LLM.
- **`src/core/llm_client.py`** — wrapper imutável do Azure OpenAI, já
  patcheado com `instructor`.

---

## Estrutura de pastas

```
project-1/
├── Dockerfile
├── README.md
├── requirements.txt
├── .gitignore
├── docs/
│   └── decisions.md           # registro das decisões de design
├── tests/
│   ├── __init__.py
│   ├── conftest.py                   # fixtures + env vars fictícias
│   ├── test_services.py              # testes unitários (com mock)
│   └── test_api.py                   # testes de integração (TestClient)
└── src/
    ├── main.py                       # FastAPI app + endpoints
    ├── api/
    │   └── schemas/
    │       ├── __init__.py           # reexporta os schemas
    │       └── analysis.py           # AnalysisRequest / AnalysisResponse
    ├── services/
    │   └── compliance_service.py     # lógica de análise (sem FastAPI)
    └── core/
        ├── llm_client.py             # AzureModel (imutável)
        └── exceptions.py             # exceções customizadas do domínio
```

---

## Pré-requisitos

- Python 3.11+ (o `Dockerfile` usa `python:3.11-slim`)
- Credenciais de um deployment do **Azure OpenAI** (chat completion)
- `pip` para instalar as dependências

---

## Configuração de credenciais

Crie um arquivo `.env` na raiz de `projects/project-1/`:

```env
AZURE_OPENAI_ENDPOINT="https://SEU-RECURSO.openai.azure.com/"
AZURE_OPENAI_KEY="sua-chave"
AZURE_OPENAI_API_VERSION="2024-06-01"
AZURE_DEPLOYMENT_NAME="nome-do-seu-deployment"
```

> O `.env` está listado no `.gitignore` e **não** deve ser versionado.

O `AzureModel` lê essas variáveis automaticamente via `python-dotenv`.

---

## Como rodar localmente

```bash
# 1. criar e ativar o virtualenv
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# macOS/Linux
source .venv/bin/activate

# 2. instalar dependências
pip install -r requirements.txt

# 3. configurar o .env (veja seção acima)

# 4. subir a API
uvicorn src.main:app --reload
```

Swagger UI: `http://127.0.0.1:8000/docs`
ReDoc: `http://127.0.0.1:8000/redoc`

---

## Como rodar com Docker

```bash
docker build -t compliance-checker .
docker run --rm -p 8000:8000 --env-file .env compliance-checker
```

A API ficará disponível em `http://127.0.0.1:8000`.

---

## Endpoints

### `GET /`

Health check simples.

**Resposta 200:**
```json
{ "status": "ok", "service": "Compliance Checker API" }
```

### `POST /analyze`

Recebe uma recomendação de investimento e retorna a análise de
conformidade.

**Request body (`AnalysisRequest`):**

| Campo              | Tipo   | Obrigatório | Descrição                                                       |
|--------------------|--------|-------------|-----------------------------------------------------------------|
| `text_to_analyze`  | string | sim (≥10 chars) | Texto da recomendação a ser analisada.                      |
| `client_profile`   | string | sim         | Perfil de risco do cliente (`conservador`, `moderado`, ...).    |

**Response body (`AnalysisResponse`):**

| Campo                | Tipo          | Descrição                                                              |
|----------------------|---------------|------------------------------------------------------------------------|
| `is_compliant`       | bool          | `true` se a recomendação é adequada ao perfil.                         |
| `reason`             | string        | Justificativa da análise.                                              |
| `mentioned_products` | array[string] | Produtos financeiros citados na recomendação (pode ser vazio).         |

**Exemplo com `curl`:**

```bash
curl -X POST http://127.0.0.1:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{
        "text_to_analyze": "Recomendo alocar 100% do patrimônio em criptomoedas alavancadas.",
        "client_profile": "conservador"
      }'
```

**Exemplo de resposta:**

```json
{
  "is_compliant": false,
  "reason": "A recomendação concentra 100% do patrimônio em um ativo de altíssimo risco, incompatível com o perfil conservador.",
  "mentioned_products": ["criptomoedas alavancadas"]
}
```

---

## Como funciona internamente

1. O endpoint recebe o JSON e valida contra `AnalysisRequest`.
2. `main.py` extrai os campos brutos (`text_to_analyze`, `client_profile`)
   e chama `analyze_text(text, client_profile)` — o service **não conhece**
   FastAPI nem schemas da API.
3. `analyze_text` monta um prompt em português pedindo ao modelo para
   julgar conformidade, justificar e listar produtos.
4. Caminho principal: usa `llm_client.client` (cliente OpenAI já
   patcheado com `instructor`) com `response_model=_LLMAnalysis`
   (modelo interno do service). O `instructor` valida a saída do
   modelo direto num Pydantic, que então é convertido em `dict`.
5. Caminho de fallback: se a extração estruturada falhar, faz uma
   chamada crua via `llm_client.invoke(...)` pedindo JSON explícito e
   tenta extrair com regex + `json.loads`. Falhas de conexão ou de
   parse são sinalizadas via exceções customizadas
   (`APIConnectionError` / `LLMResponseError`).
6. `main.py` recebe o `dict` do service e o serializa via
   `response_model=AnalysisResponse`. Se o service lançar uma exceção
   customizada, ela é traduzida em `HTTPException` com o status code
   correto (ver tabela em "Tratamento de erros").

---

## Tratamento de erros

Erros de domínio são representados por exceções customizadas em
`src/core/exceptions.py`. A camada de API as traduz em status HTTP:

| Exceção (service)                | Status HTTP | Quando acontece                                    |
|----------------------------------|-------------|----------------------------------------------------|
| `InvalidConfigurationError`      | **503**     | Variáveis de ambiente do `.env` ausentes.          |
| `APIConnectionError`             | **503**     | Falha ao se comunicar com o Azure OpenAI.          |
| `LLMResponseError`               | **502**     | LLM respondeu, mas a saída é inválida/vazia.       |
| Validação Pydantic               | **422**     | Payload inválido (ex.: `text_to_analyze` < 10 ch). |
| Qualquer outra exceção           | **500**     | Erro inesperado (logado com stack trace).          |

O `main.py` faz o `try/except` em volta da chamada ao service e
converte cada exceção em `HTTPException(status_code, detail)`. Veja
`docs/decisions.md` (ADR 13) para a justificativa.

---

## Testes

A suíte usa `pytest` e fica em `tests/`.

```bash
# instalar deps (já inclui pytest, httpx)
pip install -r requirements.txt

# rodar tudo
pytest

# rodar com saída detalhada
pytest -v

# rodar só os testes unitários do service
pytest tests/test_services.py
```

Cobertura:

- **`tests/test_services.py`** — testes unitários de `analyze_text`,
  com mock de `AzureModel` (não faz chamada de rede real). Valida
  caminho principal, fallback e tradução de erros em exceções.
- **`tests/test_api.py`** — testes de integração via `TestClient` do
  FastAPI. Mocka `analyze_text` para validar status codes (200, 422,
  502, 503, 500) e o schema de resposta.
- **`tests/conftest.py`** — injeta variáveis de ambiente fictícias
  para os testes não dependerem de um `.env` real.

---

## Documentação adicional

- `docs/decisions.md` — decisões de design e trade-offs assumidos no
  projeto.
