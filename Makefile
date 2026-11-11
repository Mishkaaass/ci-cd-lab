.PHONY: help doctor dashboard demo-up demo-status demo-drill tokens gitops-doctor gitops-up gitops-status gitops-ui gitops-app gitops-drift-test
.DEFAULT_GOAL := help

help:
	@bash scripts/reviewer.sh help

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
