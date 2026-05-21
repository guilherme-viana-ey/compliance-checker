# Registro de Decisões Arquiteturais (ADRs) — Projeto 1

Este documento registra as decisões de design relevantes que foram
tomadas durante a construção da **Compliance Checker API**, explicando
o contexto, a alternativa considerada, o que foi escolhido e por quê.

O formato é inspirado em ADRs leves (Architectural Decision Records).

---

## ADR 1 — Separação em camadas (`main` / `services` / `core` / `api`)

**Contexto.** A API tem responsabilidades distintas: receber HTTP,
aplicar regras de negócio e falar com o LLM. Misturar tudo em um único
arquivo dificultaria testes e a evolução futura (RAG, agentes).

**Alternativas.**
- Tudo em `main.py`. Mais rápido de escrever, mas inviável para
  evoluir.
- Camadas finas com módulos dedicados.

**Decisão.** Adotar quatro camadas:

| Camada                          | Responsabilidade                                      |
|---------------------------------|-------------------------------------------------------|
| `src/main.py`                   | Transport HTTP (FastAPI), roteamento, validação.      |
| `src/api/schemas.py`            | Contratos Pydantic de entrada/saída.                  |
| `src/services/compliance_service.py` | Regra de negócio e orquestração do LLM.          |
| `src/core/llm_client.py`        | Wrapper de baixo nível para Azure OpenAI (imutável).  |

**Consequências.** O endpoint não conhece detalhes do LLM. Trocar de
provedor (Azure → outro) só exige mexer em `core/`. O service pode ser
testado com um `AzureModel` mockado.

---

## ADR 2 — Manter o `llm_client.py` como contrato imutável

**Contexto.** O arquivo `src/core/llm_client.py` é entregue pronto e
não deve ser alterado. Ele expõe:

- `AzureModel()` — instancia com config do `.env`.
- `.client` — cliente OpenAI já patcheado com `instructor`.
- `.deployment` — nome do deployment a usar como `model`.
- `.invoke(prompt=...)` — chamada crua, devolve `ChatCompletion`.

**Alternativas.**
- Acessar atributos internos (`_base_client`, `temperature`...) para
  ganhar flexibilidade.
- Restringir o uso ao contrato público apenas.

**Decisão.** Usar **somente** o que é público: `.client`, `.deployment`
e `.invoke()`. Atributos com `_` ou detalhes de implementação são
tratados como off-limits.

**Consequências.** O service continuará funcionando mesmo se a equipe
dona do `llm_client` mexer na implementação interna, desde que o
contrato público seja preservado.

---

## ADR 3 — `instructor` como caminho principal de extração estruturada

**Contexto.** Precisamos garantir que a resposta do LLM se encaixe
exatamente em `AnalysisResult` (campos `is_compliant`, `reason`,
`mentioned_products`). Texto livre exigiria parsing manual frágil.

**Alternativas.**
1. Texto livre + regex/`json.loads` em cima da resposta.
2. `function calling` nativo da OpenAI.
3. `instructor`, que já patcheia o cliente e aceita
   `response_model=AnalysisResult`.

**Decisão.** Usar `instructor` como caminho principal. O `AzureModel`
já entrega o cliente patcheado em `self.client`, então é o uso
"pretendido" da biblioteca.

```python
llm_client.client.chat.completions.create(
    model=llm_client.deployment,
    response_model=AnalysisResult,
    messages=[{"role": "user", "content": prompt}],
)
```

**Consequências.** A validação Pydantic acontece de forma transparente
e a tipagem do retorno é correta. Dependência adicional (`instructor`),
mas é leve e já estava em `requirements.txt`.

---

## ADR 4 — Fallback determinístico em duas etapas

**Contexto.** O `instructor` pode falhar (modelo devolve algo
inesperado, erro de rede, etc.). Não queremos que a API quebre
totalmente.

**Decisão.** Implementar fallback em duas etapas dentro de
`analyze_recommendation`:

1. **Tentativa 1 (preferida).** `instructor` com `response_model`.
2. **Tentativa 2.** `llm_client.invoke(...)` pedindo JSON explícito;
   extrair com regex (`\{.*\}`) e `json.loads`.
3. **Tentativa 3 (último recurso).** Heurística textual: se a palavra
   "não" aparece, considerar como `is_compliant=false` e devolver o
   conteúdo bruto em `reason`.

**Consequências.** A API sempre devolve uma resposta no formato
esperado, mesmo em cenários degradados. O custo é que silenciosamente
podemos retornar uma análise menos confiável — por isso o ADR 6 prevê
melhorar o tratamento de erros HTTP.

---

## ADR 5 — Prompt em português, com instruções explícitas

**Contexto.** O cliente final é um analista brasileiro analisando
recomendações em português. O modelo precisa de instruções claras
sobre formato e papel.

**Decisão.**

- Definir o papel logo no início: *"Você é um analista de compliance
  de serviços financeiros. Seja rigoroso."*
- Listar as tarefas numeradas (julgar conformidade → justificar →
  listar produtos), o que reduz omissões.
- Delimitar o texto da recomendação com aspas triplas (`"""..."""`)
  para evitar ambiguidade entre instrução e dado.
- No fallback, anexar instrução explícita de "responda exclusivamente
  com um JSON válido" — necessário porque, sem `response_model`, o
  modelo tende a "explicar" a resposta.

**Consequências.** Prompt mais longo, porém muito mais previsível.

---

## ADR 6 — Erros virando `AnalysisResult` (em vez de HTTP 5xx) — **temporário**

**Contexto.** Hoje, qualquer exceção é capturada e devolvida como
`AnalysisResult(is_compliant=false, reason="Falha: ...")`. Isso simplifica
o fluxo, mas mascara erros de infraestrutura como "análise negativa".

**Decisão (atual).** Manter o comportamento para a primeira versão,
prioritizando disponibilidade e simplicidade do contrato.

**Plano de evolução.**
- Lançar `HTTPException(502)` quando a chamada ao LLM falhar.
- Lançar `HTTPException(503)` se o `AzureModel` não conseguir
  inicializar (credenciais ausentes).
- Adicionar um *middleware* para logar a stack trace, mantendo a
  resposta enxuta para o cliente.

**Consequências.** Trade-off consciente: simplicidade agora, semântica
HTTP correta depois.

---

## ADR 7 — Configuração via `.env` + `python-dotenv`

**Contexto.** Precisamos de um jeito padrão e seguro de injetar
credenciais sem hard-coding nem comitar segredos.

**Alternativas.** Variáveis exportadas no shell, Vault, AWS Secrets
Manager, `.env`.

**Decisão.** Usar `.env` carregado por `python-dotenv` (já é o que o
`llm_client.py` espera). `.env` está no `.gitignore`, e o `Dockerfile`
recebe credenciais via `--env-file` em runtime.

**Consequências.** Setup local trivial. Para produção, basta trocar o
`.env` por um Secret Manager — o código não precisa mudar, já que lê
de `os.getenv(...)`.

---

## ADR 8 — FastAPI + Pydantic v2 + Uvicorn

**Contexto.** Precisamos de uma API HTTP simples, com docs automáticas
e validação forte de payload.

**Alternativas.** Flask + marshmallow, Django REST, raw Starlette.

**Decisão.** **FastAPI** porque:

- Integra nativamente com Pydantic — os schemas viram contrato e doc.
- Gera Swagger UI (`/docs`) e ReDoc (`/redoc`) sem configuração extra.
- `uvicorn` é o servidor recomendado, com hot-reload para desenvolvimento.

**Consequências.** Ecossistema muito alinhado ao que `instructor` e
`openai` esperam. Curva de aprendizado curta.

---

## ADR 9 — Docker com `python:3.11-slim` e `--reload` desligado

**Contexto.** Precisamos de uma imagem leve e reprodutível para
deploy.

**Decisão.** `Dockerfile` baseado em `python:3.11-slim`, instalando
apenas o `requirements.txt`, copiando o código e expondo a porta 8000.
O `CMD` roda `uvicorn src.main:app --host 0.0.0.0 --port 8000` (sem
`--reload`, que é apenas para desenvolvimento).

**Consequências.** Imagem pequena e previsível. Para desenvolvimento
local fora do container, ainda usamos `uvicorn ... --reload`.

---

## ADR 10b — Desacoplamento do `service` em relação aos schemas da API

**Contexto.** Numa versão anterior, `analyze_recommendation` recebia
um `AnalysisRequest` e retornava `AnalysisResult` — ambos definidos em
`src/api/schemas/`. Isso fazia o service **importar a camada de API**,
violando a regra "lógica de negócio não conhece HTTP".

**Decisão.** Reescrever a função pública do service para:

- Receber argumentos primitivos: `analyze_text(text: str, client_profile: str)`.
- Retornar `Dict[str, Any]` plano com as chaves do domínio.
- Manter um modelo Pydantic **interno** (`_LLMAnalysis`, com underline)
  apenas para a extração estruturada via `instructor`. Esse modelo é
  detalhe de implementação e nunca é exposto.

A tradução `dict ↔ AnalysisResponse` acontece em `src/main.py`, que é
a única camada que conhece HTTP e Pydantic da API.

**Consequências.**
- O service pode ser chamado por uma CLI, um agente autônomo (próximos
  projetos), ou por testes unitários, sem precisar montar um
  `AnalysisRequest`.
- O contrato HTTP (`AnalysisResponse`) pode evoluir sem mexer no
  service, e vice-versa.
- Custo: uma camada extra de conversão no endpoint
  (`AnalysisResponse(**result)`), trivial.

---

## ADR 11 — `src/api/schemas/` como pacote (diretório), não arquivo único

**Contexto.** Começamos com `src/api/schemas.py`. Conforme o domínio
crescer (compliance, portfolio, KYC, etc.), um único arquivo vira um
gargalo de merge e leitura.

**Decisão.** Converter para pacote:

```
src/api/schemas/
├── __init__.py     # reexporta os schemas para imports curtos
└── analysis.py     # schemas do domínio de análise
```

O `__init__.py` reexporta `AnalysisRequest` e `AnalysisResponse`, então
os imports externos não mudam:

```python
from src.api.schemas import AnalysisRequest, AnalysisResponse
```

**Consequências.** Cada domínio futuro vira um arquivo próprio
(`schemas/portfolio.py`, `schemas/kyc.py`...), sem refator dos imports.

---

## ADR 12 — Nomenclatura: `AnalysisResponse` e `text_to_analyze`

**Contexto.** A versão anterior usava `AnalysisResult` e o campo `text`.

**Decisão.** Alinhar com o padrão do programa:

- Classe: `AnalysisResponse` (deixa claro que é "resposta da API",
  pareando com `AnalysisRequest`).
- Campo: `text_to_analyze` (mais descritivo que `text`, evita colisão
  semântica em payloads futuros que tenham outros campos textuais).
- Validação: `min_length=10` no `text_to_analyze` (rejeita
  recomendações vazias/triviais já na borda HTTP).

**Consequências.** API mais autodescritiva e validação acontecendo no
ponto mais barato (antes de chegar no LLM).

---

## ADR 13 — Exceções customizadas em `src/core/exceptions.py`

**Contexto.** A versão inicial (ADR 6) capturava todos os erros no
service e devolvia um `AnalysisResult(is_compliant=false, reason=...)`.
Isso mascarava erros de infraestrutura como "análise negativa" — o
cliente HTTP recebia 200 OK mesmo em cenários de falha real.

**Decisão.** Criar uma hierarquia de exceções específicas do domínio:

```
ComplianceCheckerError                (base)
├── InvalidConfigurationError         -> 503 (env vars ausentes)
├── APIConnectionError                -> 503 (falha de rede com o LLM)
└── LLMResponseError                  -> 502 (LLM respondeu, mas inválido)
```

- O **service** detecta a causa raiz e lança a exceção apropriada
  (ainda usando o fallback de duas etapas).
- A **camada de API** (`src/main.py`) captura essas exceções num
  bloco `try/except` e usa `raise HTTPException(status_code, detail)`
  para devolver o status HTTP correto.
- Qualquer exceção não prevista vira **500** com log de stack trace.

**Consequências.**
- Cliente HTTP recebe status codes semanticamente corretos
  (503 = serviço indisponível, 502 = upstream ruim, 422 = payload
  inválido, 500 = bug).
- O service continua sem conhecer FastAPI — só lança exceções; quem
  decide o que fazer com elas é o `main.py`.
- ADR 6 está formalmente revogada por esta.

---

## ADR 14 — Suíte de testes com `pytest` (unitários + integração)

**Contexto.** Sem testes, qualquer mudança no service ou no schema
podia quebrar a API silenciosamente. Precisamos de uma rede de
segurança que rode rápido (sem depender do Azure OpenAI).

**Decisão.** Suíte `pytest` em `tests/` com duas camadas:

1. **`tests/test_services.py` — unitários.**
   - Mockam `AzureModel` via `unittest.mock.patch`.
   - Cobrem: caminho principal (`instructor`), fallback (`invoke` +
     parse), e cada exceção customizada (`InvalidConfigurationError`,
     `APIConnectionError`, `LLMResponseError`).
   - Não fazem chamada de rede real → executam em ms.

2. **`tests/test_api.py` — integração.**
   - Usam `fastapi.testclient.TestClient` para chamadas HTTP reais ao
     `app`.
   - Mockam `src.main.analyze_text` para isolar a camada HTTP.
   - Validam: 200 (happy path), 422 (Pydantic), 502/503/500
     (tradução de exceções).

3. **`tests/conftest.py`** injeta env vars fictícias para que a
   importação do `AzureModel` não exploda em CI.

**Alternativas descartadas.**
- Só integração: lento, frágil, depende de credenciais.
- Só unitário: não cobre tradução de exceções nem validação Pydantic.

**Consequências.**
- `requirements.txt` ganhou `pytest` e `httpx` (dependência do
  `TestClient` no FastAPI moderno).
- CI pode rodar `pytest` sem secrets configurados.
- Custo: 2 arquivos novos (~150 linhas) e uma fixture global.

---

## ADR 10 — `mentioned_products` como `List[str]`, não como objeto rico

**Contexto.** Em princípio, cada produto poderia ter `nome`,
`categoria`, `nível de risco`, etc.

**Decisão.** Manter como `List[str]` na versão inicial.

**Motivação.** YAGNI. Para o caso de uso atual (triagem de
recomendações), a lista textual já é suficiente. Quando o agente
autônomo (próximo projeto) precisar correlacionar produtos com uma
base de conhecimento, evoluímos para um objeto estruturado sem
quebrar o contrato (campo adicional ou versão `v2` do endpoint).

---
