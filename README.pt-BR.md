# a2a-otel-kit

[English](README.md)

> **Tracing distribuído, independente de fornecedor, para agentes A2A e serviços MCP.**

Conecte chamadas entre agentes e MCP em um único trace OpenTelemetry usando W3C Trace Context - sem capturar prompts, mensagens, credenciais ou payloads de negócio.

[![PyPI](https://img.shields.io/pypi/v/a2a-otel-kit)](https://pypi.org/project/a2a-otel-kit/)
[![Python](https://img.shields.io/pypi/pyversions/a2a-otel-kit)](https://pypi.org/project/a2a-otel-kit/)
[![Quality](https://github.com/brunovicco/a2a-otel-kit/actions/workflows/quality.yml/badge.svg)](https://github.com/brunovicco/a2a-otel-kit/actions/workflows/quality.yml)
[![License](https://img.shields.io/github/license/brunovicco/a2a-otel-kit)](LICENSE)

<p align="center">
  <img src="docs/assets/architecture.png" alt="Arquitetura do a2a-otel-kit" width="920">
</p>

## Por que este projeto existe

Sistemas agênticos raramente executam dentro de um único processo.

Uma única requisição pode atravessar um orquestrador, um ou mais agentes A2A, servidores MCP, fronteiras HTTP e serviços downstream. Sem propagação explícita do contexto de trace, cada salto se transforma em uma ilha de telemetria, e o diagnóstico passa a depender de correlação manual por timestamps e suposições.

O `a2a-otel-kit` fornece uma camada focada de observabilidade para essas interações distribuídas:

- tracing OpenTelemetry exportado via OTLP/HTTP;
- propagação W3C de `traceparent` e `tracestate`;
- instrumentação de cliente e servidor A2A;
- instrumentação de cliente e servidor MCP Streamable HTTP;
- eventos JSON estruturados correlacionados com traces ativos;
- atributos de telemetria seguros, com política deny-by-default;
- ciclo de vida explícito com `flush()` e `shutdown()`;
- nenhuma dependência de SDKs de Datadog, Langfuse ou outro fornecedor de observabilidade.

**Uma requisição de negócio. Múltiplos agentes. Múltiplos protocolos. Um único trace distribuído.**

## O que o projeto oferece

| Capacidade | Suporte |
| --- | --- |
| Spans OpenTelemetry | ✅ |
| Exportação OTLP/HTTP | ✅ |
| W3C Trace Context | ✅ |
| Eventos JSON estruturados | ✅ |
| Tracing de cliente A2A | ✅ |
| Tracing de servidor A2A | ✅ JSON-RPC / REST |
| Ciclo de vida de streaming A2A | ✅ |
| Tracing de cliente MCP | ✅ Streamable HTTP |
| Tracing de servidor MCP | ✅ Streamable HTTP |
| Sanitização de atributos com foco em privacidade | ✅ |
| Adapter de telemetria de runtime para governança | ✅ Opcional |
| Continuidade de contexto A2A via gRPC | ⚠️ Não verificada |
| MCP stdio | ❌ |
| MCP SSE legado | ❌ |

## Privacidade por design

A telemetria dos adapters A2A/MCP embutidos é **somente metadados por construção**, e não apenas
porque a captura de conteúdo está desabilitada por padrão.

| Dado | Capturado |
| --- | :---: |
| Trace ID / Span ID | ✅ |
| Nomes fixos de operações | ✅ |
| Metadados do serviço | ✅ |
| Atributos escalares permitidos | ✅ |
| Prompts | ❌ |
| Respostas do modelo | ❌ |
| Corpos de mensagens A2A | ❌ |
| Conteúdo de tasks / artifacts | ❌ |
| Argumentos e resultados MCP | ❌ |
| Headers de autorização | ❌ |
| Credenciais / secrets | ❌ |
| Mensagens de exceção nos adapters A2A/MCP fixos | ❌ |

O sanitizador mantém apenas chaves permitidas, rejeita chaves com aparência de credencial mesmo quando adicionadas explicitamente à allowlist e descarta valores não suportados ou grandes demais. Consulte o [modelo de privacidade](docs/PRIVACY.md).

Spans de aplicação criados pelo consumidor registram exceções por padrão, seguindo o
comportamento do OpenTelemetry; use `record_exception=False` quando uma exceção puder conter dados
sensíveis. Consulte a [política de segurança](SECURITY.md) para a fronteira exata.

## Quickstart em 60 segundos

Instale o pacote base:

```bash
uv add a2a-otel-kit
```

Ou instale os adapters de protocolo:

```bash
uv add "a2a-otel-kit[a2a,mcp]"
```

Configure a observabilidade:

```python
from a2a_otel_kit import Observability, ObservabilitySettings

settings = ObservabilitySettings(
    service_name="orchestrator",
    service_version="1.0.0",
    environment="local",
    enabled=True,
    otlp_endpoint="http://localhost:4318/v1/traces",
)

observability = Observability.configure(settings)
```

Crie spans de aplicação e eventos estruturados:

```python
with observability.start_span(
    "customer.lookup",
    attributes={"operation": "customer_lookup"},
):
    observability.emit_event(
        "customer.lookup.completed",
        "success",
        operation="customer_lookup",
    )
```

Sempre libere os recursos do exporter durante o encerramento da aplicação:

```python
try:
    ...
finally:
    observability.flush()
    observability.shutdown()
```

Quando `enabled=False`, o tracing se torna um no-op e o código consumidor não precisa criar lógica condicional específica.

## Trace end-to-end

Uma interação real da demo executável segue esta topologia:

```text
orchestrator
└── demo.risk_assessment
    └── a2a.client.get_task
        └── risk-agent / a2a.server.on_get_task
            ├── mcp.client.streamable_http
            │   └── customer-data-mcp / mcp.server.streamable_http
            ├── mcp.client.streamable_http
            │   └── customer-data-mcp / mcp.server.streamable_http
            └── ...
```

O span da operação é criado antes da injeção do contexto W3C, permitindo que o trabalho downstream em A2A e MCP continue no mesmo trace distribuído.

<p align="center">
  <img src="docs/assets/trace-flow.png" alt="Fluxo distribuído de trace entre A2A e MCP" width="920">
</p>

### Prova end-to-end real

O repositório inclui uma demo local executável com Orchestrator, A2A Risk Agent, Customer Data MCP, OpenTelemetry Collector, Tempo e Grafana.

A demonstração de 20 segundos mostra a execução, a verificação bem-sucedida e o trace distribuído no Grafana:

<p align="center">
  <img src="docs/assets/demo/demo.gif" alt="Demo end-to-end de observabilidade A2A e MCP exibindo o trace distribuído no Grafana Tempo" width="1100">
</p>

O trace final também está disponível como captura estática:

<p align="center">
  <img src="docs/assets/demo/trace.png" alt="Trace distribuído real entre A2A e MCP capturado no Grafana Tempo" width="1100">
</p>

Nessa execução:

- **3 serviços** participam do mesmo trace distribuído: `orchestrator`, `risk-agent` e `customer-data-mcp`;
- o trace contém **11 spans**;
- o contexto A2A client/server é preservado na fronteira entre os agentes;
- o contexto MCP Streamable HTTP client/server continua o mesmo trace;
- múltiplos spans MCP são esperados porque uma sessão MCP real executa operações de protocolo além da chamada da tool de negócio;
- o verificador exige que os spans A2A e MCP resolvam para o mesmo `trace_id`;
- um identificador privado é propositalmente incluído na resposta de negócio e verificado como ausente da telemetria exportada.

Execute a prova localmente:

```bash
docker compose -f examples/end_to_end/compose.yml up -d
uv run python examples/end_to_end/run_demo.py
uv run python examples/end_to_end/verify_trace.py
```

Uma verificação bem-sucedida termina com:

```text
✓ A2A client span found
✓ A2A server span found
✓ MCP client span found
✓ MCP server span found
✓ Required spans share one trace_id
✓ Private business identifier absent from current trace telemetry

Demo verification: PASSED
```

A demo é intencionalmente focada: ela prova a continuidade do trace distribuído através das fronteiras A2A e MCP e o modelo de telemetria somente com metadados. Ela não adiciona LLM, banco de dados, framework de agentes ou dependência de cloud apenas para tornar o exemplo mais complexo.

## Integração A2A

Instale:

```bash
uv add "a2a-otel-kit[a2a]"
```

Chamadas de saída encapsulam o cliente oficial A2A:

```python
from a2a_otel_kit.adapters.a2a import TracingClient

client = TracingClient.wrap(real_client, observability)

async for event in client.send_message(request):
    ...
```

Requisições de entrada JSON-RPC / REST encapsulam o request handler oficial:

```python
from a2a_otel_kit.adapters.a2a import TracingRequestHandler

request_handler = TracingRequestHandler.wrap(
    real_handler,
    observability,
)
```

O adapter registra apenas metadados fixos de operação e de baixa cardinalidade. Ele não registra nomes de agentes, corpos de mensagens, conteúdo de artifacts, headers arbitrários, URLs ou texto de exceções.

Operações de streaming controlam explicitamente seus iteradores internos e emitem exatamente um resultado terminal para exaustão, exceção, cancelamento ou fechamento antecipado.

Consulte o [guia completo de integração A2A](docs/A2A.md).

## Integração MCP

Instale:

```bash
uv add "a2a-otel-kit[mcp]"
```

Instrumente as fronteiras públicas de Streamable HTTP:

```python
import httpx
from mcp.client.streamable_http import streamable_http_client

from a2a_otel_kit.adapters.mcp import (
    TracingASGIMiddleware,
    TracingAsyncTransport,
)

transport = TracingAsyncTransport.wrap(
    httpx.AsyncHTTPTransport(),
    observability,
)

mcp_asgi_app = TracingASGIMiddleware.wrap(
    fastmcp.streamable_http_app(),
    observability,
)

async with httpx.AsyncClient(transport=transport) as http_client:
    async with streamable_http_client(
        url,
        http_client=http_client,
    ) as streams:
        ...
```

Apenas `traceparent` e `tracestate` são propagados. Argumentos MCP, resultados, bodies, headers arbitrários, URLs e texto de exceções não são capturados.

Consulte [Integração MCP](docs/MCP.md).

## Independente de fornecedor por design

O `a2a-otel-kit` termina na fronteira do OpenTelemetry:

```text
Agent / MCP service
        │
        ▼
   a2a-otel-kit
        │
     OTLP/HTTP
        │
        ▼
OpenTelemetry Collector
   ├── Tempo
   ├── Datadog
   ├── backend compatível com Jaeger
   └── destinos definidos pelo deployment
```

Deployment do Collector, roteamento para fornecedores, credenciais, retenção e configuração do backend pertencem à plataforma consumidora.

Nenhum SDK específico de fornecedor de observabilidade é importado por este pacote.

## Telemetria de runtime para governança

Um adapter opcional pode converter um `StructuredEvent` existente para o contrato fechado de telemetria de runtime usado pelo `verifiable-ai-governance`.

```text
                         ┌──▶ OpenTelemetry / OTLP
Agent ─▶ a2a-otel-kit ───┤
                         └──▶ Governance runtime evidence
```

A entrega é intencionalmente explícita. Chamar `Observability.emit_event()` nunca executa I/O de rede inesperado para governança.

O adapter de governança sanitiza novamente os atributos, mantém credenciais fora das configurações seguras para representação, reutiliza identificadores de eventos entre retries e exige HTTPS para endpoints que não sejam loopback.

Consulte [Integração com governança](docs/GOVERNANCE.md).

## Arquitetura

O pacote segue uma direção de dependências explicitamente imposta:

```text
src/a2a_otel_kit/
├── domain/       # vocabulário de telemetria, sanitização, erros
├── application/  # settings e ports expostos ao consumidor
├── adapters/     # OTel, W3C, A2A, MCP, governança
└── entrypoints/  # facade explícita de composição e logging
```

```text
entrypoints ──▶ application ──▶ domain
adapters    ──▶ application / domain
domain      ──▶ nenhuma camada externa
```

Propriedades importantes de design:

- importar o pacote não executa I/O;
- nenhum tracer provider global do OpenTelemetry é instalado;
- cada instância configurada de `Observability` controla seu próprio ciclo de vida;
- SDKs opcionais A2A e MCP permanecem fora das camadas internas;
- adapters de protocolo instrumentam fronteiras públicas;
- regras de privacidade ficam abaixo dos adapters específicos de transporte;
- regras arquiteturais são validadas pelas ferramentas do repositório.

Leia [Arquitetura](docs/ARCHITECTURE.md) e os [ADRs](docs/adr/).

## O que é - e o que não é

| `a2a-otel-kit` é | `a2a-otel-kit` não é |
| --- | --- |
| Fundação para tracing distribuído | Um backend de observabilidade |
| Instrumentação A2A / MCP | Um framework de agentes |
| Propagação de contexto W3C | Um deployment de Collector |
| Telemetria estruturada | Um logger de prompts |
| OTLP independente de fornecedor | Um wrapper do SDK Datadog |
| Metadados com foco em privacidade | Um gravador de conversas com LLM |
| Integração explícita em runtime | Monkey-patching automático |

## Verificação

O repositório valida mais do que a capacidade de importar o pacote:

- testes unitários cobrem sanitização, ciclo de vida, correlação, concorrência, cancelamento, streaming e privacidade;
- testes de integração loopback exercitam rotas HTTP oficiais A2A e FastMCP Streamable HTTP usando sockets TCP reais;
- uma integração opcional com Collector exporta um span e verifica seu recebimento positivo na saída do Collector;
- a CI testa as versões mínima e mais recente dentro dos limites declarados dos SDKs A2A/MCP em Python 3.13 e 3.14;
- artefatos de release são inspecionados e submetidos a smoke tests antes da publicação.

Execute o quality gate padrão:

```bash
uv sync --frozen
uv run pytest
uv run python scripts/quality_gate.py
```

Execute os testes de integração dos protocolos:

```bash
uv run pytest --no-cov -m integration \
  tests/integration/test_a2a_http.py \
  tests/integration/test_mcp_streamable_http.py
```

Execute o teste de receipt do OpenTelemetry Collector:

```bash
install -d -m 0777 .collector-receipts
install -m 0666 /dev/null .collector-receipts/traces.jsonl

docker compose -f compose.collector.yml up -d

A2A_OTEL_KIT_COLLECTOR_ENDPOINT=http://127.0.0.1:4318/v1/traces \
A2A_OTEL_KIT_COLLECTOR_RECEIPT_FILE=.collector-receipts/traces.jsonl \
uv run pytest --no-cov -m integration \
  tests/integration/test_collector_otlp.py

docker compose -f compose.collector.yml down --volumes --remove-orphans
```

O teste do Collector exige recebimento positivo: o span exportado e o nome do serviço precisam aparecer na saída do Collector. Acessibilidade do endpoint ou um `flush()` bem-sucedido do exporter, isoladamente, não são considerados prova de entrega.

## Documentação

Comece pelo [índice da documentação](docs/README.md).

| Tópico | Documento |
| --- | --- |
| Arquitetura e fronteiras | [ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Integração A2A | [A2A.md](docs/A2A.md) |
| Demo end-to-end executável | [examples/end_to_end/README.md](examples/end_to_end/README.md) |
| Integração MCP | [MCP.md](docs/MCP.md) |
| Modelo de privacidade | [PRIVACY.md](docs/PRIVACY.md) |
| Política de segurança | [SECURITY.md](SECURITY.md) |
| Modelo de ameaças | [THREAT_MODEL.md](docs/THREAT_MODEL.md) |
| Fronteira de observabilidade de LLM | [LLM_OBSERVABILITY.md](docs/LLM_OBSERVABILITY.md) |
| Integração com governança | [GOVERNANCE.md](docs/GOVERNANCE.md) |
| Benchmarks de overhead | [benchmarks/README.md](benchmarks/README.md) |
| Troubleshooting | [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) |
| Desenvolvimento e releases | [DEVELOPMENT.md](docs/DEVELOPMENT.md) |
| Como contribuir | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Decisões arquiteturais | [docs/adr/](docs/adr/) |

Exemplos importáveis de adoção estão disponíveis em [`examples/`](examples/).

## Compatibilidade

- Python: `>=3.13,<3.15`
- `a2a-sdk`: `>=1.1,<2.0`
- `mcp`: `>=1.28,<2.0`
- OpenTelemetry SDK/exporter: `>=1.43,<2.0`

Os intervalos declarados das dependências opcionais formam o contrato de compatibilidade. A CI verifica tanto as resoluções mínimas quanto as mais recentes dentro desses limites.

## Limitações

Deliberadamente fora de escopo:

- continuidade de trace context A2A via gRPC não verificada;
- MCP stdio não instrumentado;
- MCP SSE legado não instrumentado;
- deployment e retenção do Collector não pertencem à biblioteca;
- configuração específica de backends de fornecedores não pertence à biblioteca;
- headers de autenticação OTLP são resolvidos durante a configuração; rotação dinâmica de credenciais por requisição não é fornecida.

Essas são fronteiras explícitas, não caminhos sem suporte escondidos.

## Releases

O pacote é publicado no PyPI usando GitHub Actions e PyPI Trusted Publishing.

Faça o build e verifique localmente:

```bash
uv build --out-dir dist
uv run python scripts/verify_release_artifacts.py --dist-dir dist
```

Consulte [CHANGELOG.md](CHANGELOG.md) e o runbook de release em [DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Licença

MIT. Consulte [LICENSE](LICENSE).
