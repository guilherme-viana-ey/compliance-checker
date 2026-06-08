# Decisões Arquiteturais — Etapa 3: Agentes Inteligentes

---

## 1. LangGraph como Orquestrador do Agente

**Decisão:** usar LangGraph para modelar o fluxo do agente como um grafo de estados explícito.

**Por quê:**
- O fluxo de compliance tem bifurcações claras (aprovar vs. rejeitar) que mapeiam naturalmente para um grafo dirigido.
- LangGraph torna o fluxo **visível e auditável** — cada nó é uma função pura com entrada e saída bem definidas.
- O estado compartilhado (`ComplianceState`) centraliza todos os dados de uma execução, facilitando logging e rastreabilidade.
- Alternativas como LangChain `AgentExecutor` ou loops manuais são menos estruturadas e mais difíceis de debugar em produção.

**Grafo implementado:**
```
START → read_document → analyze_compliance → [approve | reject] → END
```

**Trade-off:** LangGraph adiciona dependência ao projeto. Para fluxos simples como este, um pipeline sequencial manual seria suficiente. A escolha se justifica pela extensibilidade: o grafo pode crescer com novos nós (ex: escalation, notificação por email) sem reescrever a lógica central.

---

## 2. Estado Imutável por Nó (Functional State Updates)

**Decisão:** cada nó retorna `{**state, ...novos_campos}` em vez de mutar o estado diretamente.

**Por quê:**
- Segue o padrão funcional do LangGraph, onde cada nó é uma transformação do estado.
- Facilita debugging: é possível inspecionar o estado antes e depois de cada nó.
- Evita efeitos colaterais inesperados entre nós executados em paralelo (caso o grafo seja expandido).

---

## 3. Separação entre Tools e Nós do Grafo

**Decisão:** as ações atômicas (ler arquivo, analisar, mover, alertar) ficam em `tools.py`, separadas dos nós do grafo em `compliance_agent.py`.

**Por quê:**
- **Testabilidade:** as tools podem ser testadas unitariamente sem instanciar o grafo LangGraph.
- **Reusabilidade:** as mesmas tools podem ser usadas por um agente LLM via Tool Calling (ex: função chamada pelo GPT-4) ou por um servidor MCP — sem duplicação de código.
- **Separação de responsabilidades:** os nós orquestram (lógica de fluxo + logging), as tools executam (efeitos colaterais).

---

## 4. Guardrails de Segurança

**Decisão:** implementar guardrails em múltiplas camadas para garantir que o agente opere dentro de limites seguros.

**Guardrails implementados:**

| Camada | Guardrail | Comportamento |
|---|---|---|
| `tools.py` | Extensão de arquivo | Rejeita arquivos que não sejam .txt ou .pdf |
| `tools.py` | Tamanho máximo (500 KB) | Rejeita arquivos muito grandes |
| `tools.py` | Conteúdo vazio | Rejeita arquivos sem texto extraível |
| `watcher.py` | Arquivos temporários | Ignora arquivos começando com `.`, `~` ou `_` |
| `watcher.py` | File settle delay | Aguarda 1.5s após criação para garantir escrita completa |
| `compliance_agent.py` | Erro → rejeição | Qualquer erro no fluxo leva à rejeição (fail-safe) |
| `compliance_agent.py` | Perfil padrão | Se o perfil não for identificado, usa "moderado" |

**Princípio:** em caso de dúvida, rejeitar e alertar. É mais seguro para compliance rejeitar um caso ambíguo e escalar para revisão humana do que aprovar erroneamente.

---

## 5. Dois Modos de Operação: Batch e Watch

**Decisão:** o runner suporta `--mode batch` (processa arquivos existentes) e `--mode watch` (monitora em tempo real).

**Por quê:**
- **Batch** é ideal para processar lotes de documentos históricos, testes e demonstrações.
- **Watch** é o modo de produção real, onde o agente opera como daemon.
- Separar os modos permite testar e validar o comportamento antes de colocar em produção contínua.

---

## 6. Indicador de Automação

**Decisão:** calcular e exibir o indicador de automação ao final de cada execução batch.

**Fórmula:**
```
taxa_automacao = (documentos_aprovados + documentos_rejeitados_com_alerta) / total * 100
```

**Premissa do cálculo de eficiência:**
- Uma análise manual de compliance leva em média 15 minutos por documento (revisão, consulta de normas, registro).
- O agente processa em média em 3-5 segundos (tempo dominado pela chamada ao LLM).
- Documentos rejeitados também são automáticos: o agente já moveu o arquivo e criou o alerta — o analista humano recebe o caso pré-triado, não do zero.

**Exemplo com 20 documentos:**
```
Antes  : 20 × 15 min = 300 min (5h) de trabalho manual
Depois : 1 × 15 min  = 15 min (apenas os casos com erro crítico)
Ganho  : 285 min (4,75h) poupadas por lote
```

---

## 7. Logging Estruturado

**Decisão:** usar dois tipos de log complementares:
1. `logging` padrão do Python (formato texto) para rastreabilidade em tempo real
2. JSON estruturado (`data/logs/execution_*.json`) para auditoria e análise posterior

**Por quê:**
- O log em texto é lido por humanos em tempo real (terminal, tail -f).
- O JSON é consumido por ferramentas de análise (pandas, dashboards, ELK stack).
- O campo `execution_logs` no `ComplianceState` registra cada passo da decisão para aquele documento específico — permite reconstruir exatamente o que aconteceu em uma análise.

---

## 8. Integração com o Projeto 2 (sem HTTP)

**Decisão:** o agente chama `analyze_recommendation()` diretamente (import Python), não via HTTP para `POST /analyze`.

**Por quê:**
- Elimina latência de rede e overhead de serialização HTTP para chamadas locais.
- Evita dependência de a API estar rodando — o agente funciona standalone.
- A função `analyze_recommendation` já tem a lógica completa de RAG + fallback.

**Trade-off:** acopla o agente ao código do Projeto 2. Se a API evoluir para um serviço separado, a tool `tool_analyze_compliance` pode ser trocada para fazer uma chamada HTTP sem impactar o resto do agente.

---

## 9. watchdog para Monitoramento de Diretório

**Decisão:** usar a biblioteca `watchdog` para o modo watch, em vez de polling com `os.listdir` em loop.

**Por quê:**
- `watchdog` usa APIs nativas do SO (`inotify` no Linux, `FSEvents` no macOS, `ReadDirectoryChangesW` no Windows) — muito mais eficiente do que polling.
- Detecta eventos de criação em milissegundos, sem consumir CPU constantemente.
- API simples de `FileSystemEventHandler` é fácil de testar e de estender.

---

## Decisões em Aberto

- **MCP Server:** expor as tools via FastMCP para que o agente possa ser orquestrado por um cliente MCP (ex: Claude Desktop). A estrutura está preparada — as tools em `tools.py` são funções puras prontas para serem registradas como ferramentas MCP.
- **Observabilidade:** instrumentar com OpenTelemetry para rastrear latência por nó, tokens consumidos e taxa de erro. LangSmith pode ser integrado diretamente ao LangGraph.
- **Retry automático:** adicionar retry com backoff exponencial na tool `tool_analyze_compliance` para lidar com falhas transitórias da API Azure OpenAI.
- **Notificação real:** trocar o log de alertas por uma notificação real (email via SendGrid, Teams webhook, Slack) para os casos rejeitados.
- **Threshold de confiança:** adicionar um campo `confidence_score` na análise e criar um terceiro caminho: casos de baixa confiança vão para revisão mesmo que `is_compliant=True`.