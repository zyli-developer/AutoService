.PHONY: setup seed-cinnox run-channel run-web run-gateway run-server start dev-start stop status check e2e-web e2e-feishu pool-status pool-start pool-test sync sync-dry sync-auto sync-status sync-status-all sync-all register-fork unregister-fork refine refine-auto refine-pull sync-bridge public-build public-up public-down public-panic public-reload public-smoke public-status public-logs public-install public-uninstall access-apply generate-admin-passwords generate-operator-passwords install-smtp-config

# --- Setup ---
# Mode-aware setup delegated to scripts/setup.sh (T7S.4, spec §3.5):
#   • reads deployment_mode from .autoservice/config.local.yaml
#   • master mode → M1 behavior (links + plugin skill discovery)
#   • tenant mode → per-tenant skill isolation (plugins/<tid>/skills)
#   • init .autoservice/ runtime dirs (idempotent)
setup:
	@bash scripts/setup.sh

# Seed the cinnox tenant sandbox (config.json + souls + kb.db + chunks).
# Idempotent — safe to re-run; wipes + reseeds its own source_ids only.
# Run after `make setup` on a fresh deployment, before `make start`.
# Pass FAST=1 to skip the ~1-2 min OneSyn PDF/XLSX ingest (glossary + demo chunks only).
seed-cinnox:
	@uv run python scripts/seed_cinnox_tenant.py $(if $(FAST),--skip-file-ingest)

# --- Run ---
run-channel:
	uv run python3 channels/feishu/channel.py

run-web:
	@mkdir -p .autoservice/logs
	AUTH_DEV_MODE=1 PLACEHOLDER_ENABLED=0 uv run uvicorn channels.web.app:app --host 0.0.0.0 --port $${DEMO_PORT:-8000} --log-level info 2>&1 | tee -a .autoservice/logs/web.log

# Phase 6+ WS gateway (/ws/customer, /ws/operator, /ws/admin)
# Conversation persistence is on by default (writes to
# .autoservice/database/conversations.db). Set CONV_PERSIST=0 to disable,
# CONV_DB_PATH=<path> to relocate. Reset with scripts/reset_conversations.py.
run-gateway:
	@mkdir -p .autoservice/logs
	PLACEHOLDER_ENABLED=0 uv run uvicorn autoservice.web_gateway:create_app --factory --host 0.0.0.0 --port $${DEMO_PORT:-8000} --log-level info 2>&1 | tee -a .autoservice/logs/gateway.log

run-server:
	uv run python3 channels/feishu/channel_server.py

# --- Dev stack: gateway + 3 frontend dev servers ---
# `make start` launches everything in the background; `make stop` kills them.
# `start` defensively zeroes dev-only backend flags (AUTH_DEV_MODE /
# DREAM_DEV_STUB) so a stray `export AUTH_DEV_MODE=1` in the caller's
# shell — or an earlier `make dev-start` — does NOT leak into a `make
# start` invocation. Explicit command-line assignment beats any env var
# inherited from the parent shell.
# Logs: .autoservice/logs/{gateway,customer,operator,admin}.log
# PIDs: .autoservice/run/{gateway,customer,operator,admin}.pid
start: stop
	@mkdir -p .autoservice/logs .autoservice/run
	@echo "==> Starting backend gateway (port 8000, AUTH_DEV_MODE=0 DREAM_DEV_STUB=0)..."
	@AUTH_DEV_MODE=0 DREAM_DEV_STUB=0 uv run uvicorn autoservice.web_gateway:create_app --factory --host 0.0.0.0 --port 8000 --log-level info > .autoservice/logs/gateway.log 2>&1 & echo $$! > .autoservice/run/gateway.pid
	@echo "==> Starting customer-chat (port 5173)..."
	@bash -c 'cd frontend; pnpm dev:customer > ../.autoservice/logs/customer.log 2>&1 &  pid=$$!; cd ..; echo $$pid > .autoservice/run/customer.pid'
	@echo "==> Starting operator-console (port 5174)..."
	@bash -c 'cd frontend; pnpm dev:operator > ../.autoservice/logs/operator.log 2>&1 &  pid=$$!; cd ..; echo $$pid > .autoservice/run/operator.pid'
	@echo "==> Starting admin-portal (port 5175)..."
	@bash -c 'cd frontend; pnpm dev:admin > ../.autoservice/logs/admin.log 2>&1 &  pid=$$!; cd ..; echo $$pid > .autoservice/run/admin.pid'
	@echo ""
	@echo "  backend:          http://localhost:8000  (gateway)"
	@echo "  customer-chat:    http://localhost:5173"
	@echo "  operator-console: http://localhost:5174"
	@echo "  admin-portal:     http://localhost:5175"
	@echo ""
	@echo "  logs: .autoservice/logs/{gateway,customer,operator,admin}.log"
	@echo "  stop: make stop"

# Same service shape as `start`, but with AUTH_DEV_MODE=1 so admin portal
# dev-login works without SMTP. Do NOT use on prod/staging — see
# CLAUDE.md "Dev Auth Bypass". Independent recipe so `start` can
# defensively force AUTH_DEV_MODE=0 without cross-talk.
dev-start: stop
	@mkdir -p .autoservice/logs .autoservice/run
	@echo "==> Starting backend gateway (port 8000, AUTH_DEV_MODE=1)..."
	@AUTH_DEV_MODE=1 uv run uvicorn autoservice.web_gateway:create_app --factory --host 0.0.0.0 --port 8000 --log-level info > .autoservice/logs/gateway.log 2>&1 & echo $$! > .autoservice/run/gateway.pid
	@echo "==> Starting customer-chat (port 5173)..."
	@bash -c 'cd frontend; pnpm dev:customer > ../.autoservice/logs/customer.log 2>&1 &  pid=$$!; cd ..; echo $$pid > .autoservice/run/customer.pid'
	@echo "==> Starting operator-console (port 5174)..."
	@bash -c 'cd frontend; pnpm dev:operator > ../.autoservice/logs/operator.log 2>&1 &  pid=$$!; cd ..; echo $$pid > .autoservice/run/operator.pid'
	@echo "==> Starting admin-portal (port 5175)..."
	@bash -c 'cd frontend; pnpm dev:admin > ../.autoservice/logs/admin.log 2>&1 &  pid=$$!; cd ..; echo $$pid > .autoservice/run/admin.pid'
	@echo ""
	@echo "  backend:          http://localhost:8000  (gateway, AUTH_DEV_MODE=1)"
	@echo "  customer-chat:    http://localhost:5173"
	@echo "  operator-console: http://localhost:5174"
	@echo "  admin-portal:     http://localhost:5175"
	@echo ""
	@echo "  logs: .autoservice/logs/{gateway,customer,operator,admin}.log"
	@echo "  stop: make stop"

stop:
	@if [ -d .autoservice/run ]; then \
		for name in gateway customer operator admin; do \
			pidfile=".autoservice/run/$$name.pid"; \
			if [ -f "$$pidfile" ]; then \
				pid=$$(cat "$$pidfile"); \
				if kill -0 "$$pid" 2>/dev/null; then \
					echo "  stopping $$name (pid=$$pid)"; \
					kill "$$pid" 2>/dev/null || true; \
				fi; \
				rm -f "$$pidfile"; \
			fi; \
		done; \
	fi
	@# Fallback: kill anything still holding our ports (Windows + Unix)
	@for port in 8000 5173 5174 5175; do \
		pids=$$(netstat -ano 2>/dev/null | grep LISTENING | grep ":$$port " | awk '{print $$NF}' | sort -u); \
		if [ -z "$$pids" ]; then \
			pids=$$(lsof -ti tcp:$$port 2>/dev/null); \
		fi; \
		for pid in $$pids; do \
			[ -z "$$pid" ] && continue; \
			echo "  freeing port $$port (pid=$$pid)"; \
			taskkill //F //PID "$$pid" > /dev/null 2>&1 || kill -9 "$$pid" 2>/dev/null || true; \
		done; \
	done

status:
	@echo "==> Port status"
	@for port in 8000 5173 5174 5175; do \
		line=$$(netstat -ano 2>/dev/null | grep LISTENING | grep ":$$port " | head -1); \
		if [ -n "$$line" ]; then \
			echo "  :$$port  UP    $$line"; \
		else \
			echo "  :$$port  DOWN"; \
		fi; \
	done

# --- E2E Tests ---
e2e-web:
	bash tests/e2e/test_web_chat.sh

e2e-feishu:
	uv run python3 tests/e2e/test_feishu_mock.py

# --- CC Pool ---
pool-status:
	uv run python -m autoservice.cc_pool_cli status

pool-start:
	uv run python -m autoservice.cc_pool_cli start

pool-logs:
	uv run python -m autoservice.cc_pool_cli logs

pool-test:
	uv run python tests/integration_cc_pool.py

pool-unit:
	uv run python -m pytest tests/test_cc_pool.py -v

# --- Check ---
# Verify plugin discovery by listing discovered skill symlinks.
check:
	@echo "==> Checking plugin discovery"
	@found=0; \
	for link in skills/*/; do \
		[ -L "$${link%/}" ] && { echo "  plugin skill: $${link%/}"; found=$$((found+1)); }; \
	done; \
	echo "Found $$found plugin skill(s)."

# --- Sync & Refine ---
sync:
	@bash scripts/sync.sh

sync-dry:
	@bash scripts/sync.sh --dry-run

sync-auto:
	@bash scripts/sync.sh --auto

sync-status:
	@bash scripts/sync-status.sh

sync-status-all:
	@bash scripts/sync-status.sh --all

sync-all:
	@bash scripts/sync-all.sh

# Fork registration: make register-fork REPO=owner/repo NAME=tenant
register-fork:
	@bash scripts/register-fork.sh --repo $(REPO) --name $(NAME) $(if $(CONTACT),--contact $(CONTACT)) $(if $(AUTO),--auto)

unregister-fork:
	@bash scripts/unregister-fork.sh --repo $(REPO) $(if $(STATUS),--status $(STATUS)) $(if $(AUTO),--auto)

refine:
	@bash scripts/refine.sh

# Auto refine: make refine-auto COMMIT=abc123 LAYER=L2 [PR=1]
refine-auto:
	@bash scripts/refine.sh --auto --commit $(COMMIT) --layer $(LAYER) $(if $(MSG),--message "$(MSG)") $(if $(PR),--pr)

sync-bridge:
	@bash scripts/sync-bridge.sh --last-sync --auto

# Refine pull: scan L3 forks for commits to cherry-pick into L2
# make refine-pull                          — scan all registered forks
# make refine-pull REPO=../AutoService-Cinnox  — scan a specific fork
refine-pull:
	@bash scripts/refine-pull.sh $(if $(REPO),--repo $(REPO)) $(if $(AUTO),--auto) $(if $(DRY_RUN),--dry-run) $(if $(PR),--pr)

# --- Public tunnel deploy (autoservice.ezagent.chat) ---
# Spec: docs/superpowers/specs/2026-04-24-cloudflare-tunnel-demo-deploy-design.md
# Runbook: docs/deploy/public-tunnel-runbook.md

public-build:
	@bash scripts/public-build.sh

public-up:
	@bash scripts/public-up.sh

public-down:
	@bash scripts/public-down.sh

public-panic:
	@bash scripts/public-panic.sh

public-reload:
	@bash scripts/public-reload.sh

public-smoke:
	@bash scripts/public-smoke.sh

public-status:
	@for name in gateway caddy cloudflared; do \
		pidfile=".autoservice/run/$$name.pid"; \
		if [ -f "$$pidfile" ] && ps -p $$(cat $$pidfile) -o pid= >/dev/null 2>&1; then \
			echo "$$name UP (pid=$$(cat $$pidfile))"; \
		else \
			echo "$$name DOWN"; \
		fi; \
	done

public-logs:
	@tail -n 40 -F .autoservice/logs/gateway.log .autoservice/logs/caddy.log .autoservice/logs/cloudflared.log 2>/dev/null

public-install:
	@bash scripts/install-launchd.sh

public-uninstall:
	@bash scripts/uninstall-launchd.sh

access-apply:
	@bash scripts/apply-cf-access.sh

install-smtp-config:
	@bash scripts/install-smtp-config.sh

generate-admin-passwords:
	@bash scripts/generate-admin-passwords.sh

generate-operator-passwords:
	@bash scripts/generate-operator-passwords.sh
