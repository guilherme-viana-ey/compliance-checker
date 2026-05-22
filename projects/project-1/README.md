# Decisões de Arquitetura — Compliance Checker API

Este documento registra as principais escolhas técnicas do Projeto 1, com motivação e alternativas consideradas. Serve de referência para revisões futuras e para os Projetos 2 (RAG) e 3 (Agente), que vão se apoiar nesta base.

---

## 1. FastAPI como framework web
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
**Decisão:** usar FastAPI em vez de Flask ou Django.

**Por quê:**
- Geração automática de OpenAPI/Swagger a partir dos schemas Pydantic — entregável da API "documentada" sai de graça.
- Validação de request/response baseada em Pydantic, alinhada com o resto do stack (LLM estruturado via `instructor`).
- Suporte nativo a `async`, importante quando as chamadas ao LLM forem o gargalo.
- Performance suficiente (ASGI + Starlette) sem o overhead de configuração do Django.

**Alternativas consideradas:** Flask (síncrono, validação manual), Django REST (excesso de funcionalidades para um microsserviço focado).

---

## 2. Pydantic como contrato único da API e da saída do LLM

**Decisão:** os mesmos modelos Pydantic (`AnalysisRequest`, `AnalysisResult`) definem tanto o contrato HTTP quanto a estrutura que o LLM precisa devolver.

**Por quê:**
- **Fonte única da verdade.** Se o contrato muda, muda em um lugar só — request, response e prompt ficam sincronizados.
- **Validação automática nos dois extremos.** O FastAPI rejeita payloads inválidos do cliente; o `instructor` rejeita respostas inválidas do LLM. O código de negócio só lida com dados já validados.
- **Documentação grátis.** Descrições e `examples` nos campos aparecem no Swagger UI.

**Trade-off:** acopla o formato da saída do LLM ao contrato externo. Se a API precisar evoluir sem mexer no prompt (ou vice-versa), será necessário separar em dois modelos.

---

## 3. `instructor` para forçar saída estruturada do LLM

**Decisão:** usar `instructor.from_openai(...)` para que o LLM devolva diretamente uma instância de `AnalysisResult`, em vez de fazer parse manual do texto.

**Por quê:**
- Elimina o ciclo "pede JSON → recebe markdown com ```json``` → extrai com regex → tenta `json.loads` → trata erro".
- O `instructor` faz retry automático quando o modelo devolve algo que não casa com o schema.
- Saída tipada já no consumidor — sem `dict` solto rodando pela aplicação.

**Mitigação de risco:** `compliance_service.analyze_recommendation()` mantém um **fallback em três camadas** caso o `instructor` falhe:
1. Chamada padrão pedindo JSON no prompt.
2. Extração do primeiro objeto JSON via regex.
3. Heurística textual (procura por "não" na resposta) + `AnalysisResult` de erro como último recurso.

Assim, garantimos que o endpoint sempre devolve um `AnalysisResult` válido, mesmo em condições adversas.

---

## 4. Wrapper `AzureModel` em `src/core/llm_client.py`

**Decisão:** isolar toda a comunicação com o Azure OpenAI numa classe única, em vez de instanciar o SDK em cada serviço.

**Por quê:**
- **Centraliza configuração.** As variáveis de ambiente são lidas em um único ponto; falha rápido (com mensagem clara) se algo faltar.
- **Centraliza compatibilidade.** O método `invoke()` já trata a diferença entre `max_completion_tokens` (modelos novos, ex.: gpt-4o no Azure) e `max_tokens` (modelos/rotas antigas) com fallback automático — o serviço de negócio não precisa saber disso.
- **Trocabilidade.** Se um dia mudarmos para OpenAI direto, Anthropic ou Bedrock, a alteração fica restrita a esta classe. Os serviços continuam chamando `AzureModel().invoke(...)` ou um cliente equivalente.
- **Testabilidade.** É trivial passar um mock de `AzureModel` para `compliance_service` em testes unitários.

---

## 5. Separação em camadas: `api/`, `services/`, `core/`

**Decisão:** organizar o código em três camadas com responsabilidades distintas.

| Camada      | Responsabilidade                                                  |
|-------------|-------------------------------------------------------------------|
| `api/`      | Schemas (contratos HTTP) — Pydantic puro, sem lógica de negócio   |
| `services/` | Lógica de negócio (montar prompt, orquestrar LLM, tratar erros)   |
| `core/`     | Infra reutilizável (cliente LLM, configuração)                    |

**Por quê:**
- O endpoint em `main.py` fica magro — basicamente delega para o serviço.
- O serviço pode ser chamado de outros contextos (CLI, agente do Projeto 3, job batch) sem arrastar o FastAPI junto.
- Facilita testar a lógica de negócio sem subir um servidor HTTP.

---

## 6. `python-dotenv` + `.env` para configuração

**Decisão:** credenciais via arquivo `.env` carregado por `python-dotenv`, e não hard-coded ou passadas por flag.

**Por quê:**
- Padrão do ecossistema Python — qualquer dev já espera encontrar um `.env.example` ou instruções de `.env`.
- `.env` no `.gitignore` evita vazamento acidental de chaves.
- Funciona igual em desenvolvimento local e dentro do container Docker (via `--env-file .env`).

**Para produção:** o `.env` deve ser substituído por um secret manager (Azure Key Vault, AWS Secrets Manager, variáveis injetadas pelo orquestrador). O `AzureModel` aceita os valores via construtor justamente para permitir essa troca sem mexer no código.

---

## 7. Containerização com `python:3.11-slim`

**Decisão:** imagem base `python:3.11-slim`, sem multi-stage build neste momento.

**Por quê:**
- `slim` reduz o tamanho da imagem sem o trabalho de manter uma base `alpine` (que costuma quebrar wheels de pacotes científicos).
- Versão Python fixa (3.11) evita surpresas com mudanças de minor version.
- Build simples e direto: `COPY requirements.txt` → `pip install` → `COPY .` → `CMD uvicorn`.

**Evolução futura:**
- Multi-stage build com etapa separada de `pip install` para diminuir a imagem final.
- Usuário não-root no container.
- Healthcheck no `Dockerfile` apontando para `GET /`.

---

## 8. Health check em `GET /`

**Decisão:** expor um endpoint mínimo `GET /` retornando status fixo, separado da rota de negócio.

**Por quê:**
- Probes de Kubernetes/load balancer precisam de uma rota leve e sem dependências externas (não pode bater no LLM a cada 5s).
- Smoke test trivial: se `GET /` responde 200, o servidor subiu corretamente.

---

## 9. Pastas reservadas para os próximos projetos

**Decisão:** já criar `knowledge_base/`, `src/rag/` e `src/agents/` mesmo vazios.

**Por quê:**
- Sinaliza o roadmap diretamente na estrutura do repo.
- Quando o Projeto 2 (RAG) começar, o ponto de extensão já está definido — sem precisar reabrir discussão sobre onde colocar o código.

---

## Decisões em aberto

- **Logging estruturado** (JSON) — hoje usamos `logging` padrão; revisar quando integrarmos a stack de observabilidade.
- **Rate limiting** no endpoint `/analyze` — necessário antes de expor publicamente, para proteger a cota do Azure OpenAI.
- **Cache de respostas** para prompts idênticos — pode reduzir custo significativamente em cenários de re-análise.
- **Versionamento da API** (`/v1/analyze`) — adiar até a primeira mudança incompatível de contrato.