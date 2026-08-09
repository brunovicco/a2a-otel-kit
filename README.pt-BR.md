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

## Por que este projeto existe?

Sistemas agênticos raramente executam dentro de um único processo.

Uma única requisição pode atravessar um orquestrador, múltiplos agentes A2A, servidores MCP, fronteiras HTTP e serviços downstream. Sem propagação explícita de contexto, cada salto se transforma em uma ilha de telemetria e a investigação de problemas depende de horários, logs desconectados e tentativa de correlação manual.

O `a2a-otel-kit` cria uma camada comum de observabilidade para essas interações distribuídas:

- tracing com OpenTelemetry exportado por OTLP/HTTP;
- propagação W3C `traceparent` e `tracestate`;
- instrumentação de cliente e servidor A2A;
- instrumentação de cliente e servidor MCP Streamable HTTP;
- eventos JSON estruturados correlacionados com traces ativos;
- atributos de telemetria seguros e deny-by-default;
- lifecycle explícito com flush e shutdown;
- nenhuma dependência de SDK de Datadog, Langfuse ou outro fornecedor.

**Uma requisição de negócio. Vários agentes. Vários protocolos. Um único trace distribuído.**

## O que o projeto oferece

| Capacidade | Suporte |
|---|---|
| Spans OpenTelemetry | ✅ |
| Exportação OTLP/HTTP | ✅ |
| W3C Trace Context | ✅ |
| Eventos JSON estruturados | ✅ |
| Tracing de cliente A2A | ✅ |
| Tracing de servidor A2A | ✅ JSON-RPC / REST |
| Lifecycle de streams A2A | ✅ |
| Tracing de cliente MCP | ✅ Streamable HTTP |
| Tracing de servidor MCP | ✅ Streamable HTTP |
| Sanitização de atributos | ✅ |
| Adapter de runtime telemetry para governança | ✅ Opcional |
| Continuidade A2A via gRPC | ⚠️ Não verificada |
| MCP stdio | ❌ |
| MCP SSE legado | ❌ |

## Privacidade por design

A telemetria é **somente metadados por construção**, e não apenas porque a captura de conteúdo está desabilitada.

| Dado | Capturado |
|---|:---:|
| Trace ID / Span ID | ✅ |
| Nomes fixos de operação | ✅ |
| Metadados do serviço | ✅ |
| Atributos escalares permitidos | ✅ |
| Prompts | ❌ |
| Respostas do modelo | ❌ |
| Corpo de mensagens A2A | ❌ |
| Conteúdo de tasks / artifacts | ❌ |
| Argumentos e resultados MCP | ❌ |
| Authorization headers | ❌ |
| Credenciais / segredos | ❌ |
| Mensagens de exceção | ❌ |

O sanitizador mantém apenas chaves permitidas, rejeita chaves com aparência de credencial mesmo quando adicionadas explicitamente à allowlist e descarta valores incompatíveis ou grandes demais.

Veja [Modelo de privacidade](docs/PRIVACY.md).

## Quickstart

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

Crie spans e eventos estruturados:

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

Libere os recursos do exporter durante o encerramento:

```python
try:
    ...
finally:
    observability.flush()
    observability.shutdown()
```

Com `enabled=False`, tracing vira no-op e a aplicação não precisa criar fluxos condicionais.

## Trace ponta a ponta

Uma interação instrumentada pode aparecer conceitualmente assim:

```text
orchestrator
└── a2a.client.send_message
    └── risk-agent
        └── a2a.server.on_message_send
            └── mcp.client.request
                └── customer-data-mcp
                    └── mcp.server.request
```

O span da operação é criado antes da injeção do contexto W3C, permitindo que o trabalho downstream continue o mesmo trace distribuído.

<p align="center">
  <img src="docs/assets/trace-flow.png" alt="Fluxo distribuído A2A e MCP" width="920">
</p>

## Integração A2A

Instale:

```bash
uv add "a2a-otel-kit[a2a]"
```

Chamadas outbound encapsulam o cliente oficial A2A:

```python
from a2a_otel_kit.adapters.a2a import TracingClient

client = TracingClient.wrap(real_client, observability)

async for event in client.send_message(request):
    ...
```

Requisições inbound JSON-RPC / REST encapsulam o request handler oficial:

```python
from a2a_otel_kit.adapters.a2a import TracingRequestHandler

request_handler = TracingRequestHandler.wrap(
    real_handler,
    observability,
)
```

O adapter registra somente metadados fixos e de baixa cardinalidade. Nomes de agentes, corpo das mensagens, conteúdo de artifacts, headers arbitrários, URLs e texto de exceções não são registrados.

Operações de streaming possuem ownership explícito dos iteradores internos e emitem exatamente um resultado terminal para conclusão, exceção, cancelamento ou fechamento antecipado.

Veja o [guia completo de integração A2A](docs/A2A.md).

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
```

Apenas `traceparent` e `tracestate` são propagados. Argumentos MCP, resultados, payloads, headers arbitrários, URLs e texto de exceções não são capturados.

Veja [Integração MCP](docs/MCP.md).

## Independente de fornecedor

O `a2a-otel-kit` termina na fronteira do OpenTelemetry:

```text
Agente / serviço MCP
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
   ├── backend compatível
   └── destinos definidos pela plataforma
```

Deployment do Collector, roteamento para fornecedores, credenciais, retenção e configuração do backend pertencem à plataforma que consome a biblioteca.

## Runtime telemetry para governança

Um adapter opcional converte `StructuredEvent` para o contrato fechado de runtime telemetry utilizado pelo `verifiable-ai-governance`.

```text
                         ┌──▶ OpenTelemetry / OTLP
Agente ─▶ a2a-otel-kit ──┤
                         └──▶ Evidência de governança
```

A entrega é explicitamente separada. `Observability.emit_event()` nunca dispara I/O de governança de maneira implícita.

Veja [Integração com governança](docs/GOVERNANCE.md).

## Arquitetura

A biblioteca segue uma direção de dependências validada pelo próprio repositório:

```text
src/a2a_otel_kit/
├── domain/
├── application/
├── adapters/
└── entrypoints/
```

```text
entrypoints ──▶ application ──▶ domain
adapters    ──▶ application / domain
domain      ──▶ nenhuma camada externa
```

Propriedades importantes:

- importar o pacote não executa I/O;
- não é instalado um tracer provider global;
- cada `Observability` possui lifecycle independente;
- SDKs opcionais A2A e MCP permanecem fora das camadas internas;
- adapters instrumentam fronteiras públicas;
- regras de privacidade ficam abaixo dos adapters de transporte;
- regras arquiteturais são verificadas por tooling do repositório.

Leia [Arquitetura](docs/ARCHITECTURE.md) e os [ADRs](docs/adr/).

## O que é - e o que não é

| `a2a-otel-kit` é | `a2a-otel-kit` não é |
|---|---|
| Base de tracing distribuído | Backend de observabilidade |
| Instrumentação A2A / MCP | Framework de agentes |
| Propagação W3C | Deployment do Collector |
| Telemetria estruturada | Logger de prompts |
| OTLP independente de fornecedor | Wrapper do SDK Datadog |
| Metadados privacy-safe | Gravador de conversas com LLM |
| Integração explícita | Monkey-patching automático |

## Verificação

O repositório verifica mais do que importabilidade:

- testes unitários cobrem sanitização, lifecycle, correlação, concorrência, cancelamento, streaming e privacidade;
- testes de integração loopback exercitam rotas HTTP oficiais A2A e FastMCP Streamable HTTP em sockets TCP reais;
- uma integração opcional com Collector exporta um span e verifica o recebimento positivo;
- CI exercita versões mínimas e mais recentes dentro dos limites declarados dos SDKs A2A/MCP em Python 3.13 e 3.14;
- artefatos de release são inspecionados e smoke-tested antes da publicação.

Quality gate:

```bash
uv sync --frozen
uv run pytest
uv run python scripts/quality_gate.py
```

## Documentação

Comece pelo [índice da documentação](docs/README.md).

| Tema | Documento |
|---|---|
| Arquitetura e fronteiras | [ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Integração A2A | [A2A.md](docs/A2A.md) |
| Integração MCP | [MCP.md](docs/MCP.md) |
| Modelo de privacidade | [PRIVACY.md](docs/PRIVACY.md) |
| Observabilidade de LLM | [LLM_OBSERVABILITY.md](docs/LLM_OBSERVABILITY.md) |
| Governança | [GOVERNANCE.md](docs/GOVERNANCE.md) |
| Troubleshooting | [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) |
| Desenvolvimento e releases | [DEVELOPMENT.md](docs/DEVELOPMENT.md) |
| Decisões arquiteturais | [docs/adr/](docs/adr/) |

Exemplos importáveis estão em [`examples/`](examples/).

## Compatibilidade

- Python: `>=3.13,<3.15`
- `a2a-sdk`: `>=1.1,<2.0`
- `mcp`: `>=1.28,<2.0`
- OpenTelemetry SDK/exporter: `>=1.43,<2.0`

## Limitações

Fora de escopo de forma deliberada:

- continuidade de trace A2A via gRPC não está verificada;
- MCP stdio não é instrumentado;
- MCP SSE legado não é instrumentado;
- deployment e retenção do Collector não pertencem à biblioteca;
- configuração de backends específicos não pertence à biblioteca;
- headers de autenticação OTLP são resolvidos durante a configuração, sem rotação dinâmica por requisição.

## Releases

O pacote é publicado no PyPI por GitHub Actions usando PyPI Trusted Publishing.

```bash
uv build --out-dir dist
uv run python scripts/verify_release_artifacts.py --dist-dir dist
```

Veja [CHANGELOG.md](CHANGELOG.md) e o runbook de release em [DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Licença

MIT. Veja [LICENSE](LICENSE).
