# Decisões de Arquitetura — Compliance Checker API

Este documento registra as principais escolhas técnicas do Projeto 1, com motivação e alternativas consideradas. Serve de referência para revisões futuras e para os Projetos 2 (RAG) e 3 (Agente), que vão se apoiar nesta base.

---

## 1. FastAPI como framework web

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