SHELL := /bin/bash

REPO_ROOT := ../..
COMPOSE := docker compose -f compose.yml
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
	@mkdir -p $(REPO_ROOT)/.demo-receipts
	$(COMPOSE) up -d
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
