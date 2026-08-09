SHELL := /bin/bash

REPO_ROOT := ../..
DEMO_UID := $(shell id -u)
DEMO_GID := $(shell id -g)
# Match the Collector to the owner of the bind-mounted receipt without elevating privileges.
COMPOSE := A2A_OTEL_DEMO_UID=$(DEMO_UID) A2A_OTEL_DEMO_GID=$(DEMO_GID) docker compose -f compose.yml
PYTHON := uv run python

.PHONY: help demo demo-up demo-run demo-verify demo-down demo-clean demo-reset demo-trace-id demo-status

help:
	@echo "a2a-otel-kit end-to-end demo"
	@echo
	@echo "Targets:"
	@echo "  demo          Start stack, run demo, and verify"
	@echo "  demo-up       Start Collector, Tempo, and Grafana"
	@echo "  demo-run      Run the traced A2A -> MCP request"
	@echo "  demo-verify   Verify topology and privacy"
	@echo "  demo-down     Stop the observability stack"
	@echo "  demo-clean    Remove local demo receipts (stack must be stopped)"
	@echo "  demo-reset    Stop, clean receipts, and restart the stack"
	@echo "  demo-trace-id Print the latest trace ID"
	@echo "  demo-status   Show Docker Compose service status"

demo: demo-up demo-run demo-verify
	@echo
	@echo "Demo complete."
	@echo "Grafana: http://localhost:3000"
	@echo -n "Latest Trace ID: "
	@cat $(REPO_ROOT)/.demo-receipts/last_trace_id.txt

demo-up:
	@umask 077; \
		mkdir -p $(REPO_ROOT)/.demo-receipts; \
		touch $(REPO_ROOT)/.demo-receipts/traces.jsonl; \
		chmod 0700 $(REPO_ROOT)/.demo-receipts; \
		chmod 0600 $(REPO_ROOT)/.demo-receipts/traces.jsonl
	$(COMPOSE) up -d
	@for attempt in {1..30}; do \
		if curl --fail --silent --show-error \
			--connect-timeout 1 \
			--max-time 2 \
			--header "Content-Type: application/x-protobuf" \
			--data-binary "" \
			http://127.0.0.1:4318/v1/traces >/dev/null; then \
			exit 0; \
		fi; \
		if ! $(COMPOSE) ps --status running --services \
			| grep --quiet --line-regexp collector; then \
			$(COMPOSE) logs collector; \
			exit 1; \
		fi; \
		sleep 1; \
	done; \
	$(COMPOSE) logs collector; \
	exit 1
	@echo "Grafana: http://localhost:3000"

demo-run:
	cd $(REPO_ROOT) && $(PYTHON) examples/end_to_end/run_demo.py

demo-verify:
	cd $(REPO_ROOT) && $(PYTHON) examples/end_to_end/verify_trace.py

demo-down:
	$(COMPOSE) down --volumes --remove-orphans

demo-clean:
	@if $(COMPOSE) ps --status running --quiet | grep -q .; then \
		echo "Refusing to remove .demo-receipts while demo containers are running."; \
		echo "Run 'make demo-down' first."; \
		exit 1; \
	fi
	rm -rf $(REPO_ROOT)/.demo-receipts
	@echo "Removed .demo-receipts"

demo-reset: demo-down demo-clean demo-up
	@echo "Demo environment reset."

demo-trace-id:
	@cat $(REPO_ROOT)/.demo-receipts/last_trace_id.txt

demo-status:
	$(COMPOSE) ps
