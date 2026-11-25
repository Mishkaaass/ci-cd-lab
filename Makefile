.PHONY: help requirements setup setup-dev viewer showcase doctor dashboard demo-up demo-status demo-drill tokens gitops-doctor gitops-up gitops-status gitops-ui gitops-app gitops-drift-test
.DEFAULT_GOAL := help

help:
	@printf '%s\n' 'FIRST-TIME REVIEWER:' \
	  '  make requirements   - read-only required/optional tool inventory' \
	  '  make setup          - create/reuse project Python 3.14 .venv (no pip installs)' \
	  '  make viewer         - read-only Unified Console on 127.0.0.1:18002' \
	  '  make showcase       - two REAL local Docker/GitOps drills; changes own lab' \
	  '  make setup-dev      - explicitly install pinned developer dependencies in .venv' \
	  '' 'MORE / LEGACY COMMANDS:'
	@bash scripts/reviewer.sh help

requirements:
	@bash scripts/requirements.sh

setup:
	@bash scripts/setup-venv.sh

setup-dev:
	@bash scripts/setup-venv.sh --dev

viewer: setup
	@bash scripts/unified-console.sh serve

showcase: setup
	@bash scripts/showcase.sh

doctor:
	@bash scripts/reviewer.sh doctor

dashboard:
	@bash scripts/reviewer.sh dashboard

demo-up:
	@bash scripts/reviewer.sh up

demo-status:
	@bash scripts/reviewer.sh status

demo-drill:
	@bash scripts/reviewer.sh drill

tokens:
	@bash scripts/reviewer.sh tokens

gitops-doctor:
	@bash scripts/gitops-demo.sh doctor

gitops-up:
	@bash scripts/gitops-demo.sh up

gitops-status:
	@bash scripts/gitops-demo.sh status

gitops-ui:
	@bash scripts/gitops-demo.sh ui

gitops-app:
	@bash scripts/gitops-demo.sh app

gitops-drift-test:
	@bash scripts/gitops-demo.sh drift-test
