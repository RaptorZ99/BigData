# EDS CHU — points d'entrée du projet.
# `make demo` part de zéro et amène jusqu'aux dashboards.

.DEFAULT_GOAL := help
SHELL := /bin/bash

# Toutes les commandes lisent .env ; on le crée à partir de l'exemple si besoin.
ENV_FILE := .env

.PHONY: help env up down pipeline provision demo test test-e2e lint fmt reset logs status quality diagram

help: ## Affiche cette aide
	@# Le motif accepte les chiffres : sans quoi une cible comme `test-e2e`
	@# resterait invisible dans l'aide tout en étant documentée ailleurs.
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

$(ENV_FILE):
	@cp .env.example $(ENV_FILE)
	@echo "→ .env créé depuis .env.example."
	@echo "  ⚠ Pensez à y mettre un vrai sel : openssl rand -hex 32"

env: $(ENV_FILE) ## Crée .env depuis .env.example s'il n'existe pas

up: env ## Démarre ClickHouse + Metabase, puis provisionne l'entrepôt
	@# Le lake doit exister avant le démarrage : Docker le monte dans ClickHouse,
	@# et un montage créé sur un dossier absent devient invalide s'il est recréé.
	@mkdir -p data/lake data/clickhouse data/metabase
	docker compose up -d
	@echo "→ Attente de ClickHouse…"
	@until docker compose exec -T clickhouse wget -q --spider http://localhost:8123/ping 2>/dev/null; do sleep 2; done
	@echo "→ ClickHouse prêt."
	uv run eds provision-warehouse

down: ## Arrête les conteneurs (les données sont conservées)
	docker compose down

pipeline: ## Exécute le pipeline incrémental (jours non encore ingérés)
	uv run eds run

provision: ## (Re)crée les connexions, groupes, users et dashboards Metabase
	uv run eds provision-metabase

demo: up pipeline provision ## Démo complète : démarrage + ingestion + dashboards
	@# Les identifiants sont affichés juste au-dessus par `eds provision-metabase`,
	@# qui les lit dans .env : ils ne sont pas dupliqués ici, pour qu'ils ne
	@# puissent jamais devenir faux.
	@echo ""
	@echo "═══════════════════════════════════════════════════════════════"
	@echo "  EDS CHU — prêt."
	@echo "═══════════════════════════════════════════════════════════════"
	@echo "  Dashboards   http://localhost:3000"
	@echo "               (identifiants affichés ci-dessus, définis dans .env)"
	@echo "  Console SQL  http://localhost:8123/play"
	@echo ""
	@echo "  Vérifier :   make status · make quality · make test-e2e"
	@echo "               uv run eds check-cloisonnement"
	@echo "═══════════════════════════════════════════════════════════════"

status: ## État de l'ingestion et comptages par couche
	uv run eds status

quality: ## Rapport qualité du dernier run
	uv run eds quality

test: ## Tests unitaires (sans Docker)
	uv run pytest -m "not integration" -q

test-e2e: ## Tests d'intégration (nécessite make up && make pipeline)
	uv run pytest -m integration -q

lint: ## Vérifie le style du code
	uv run ruff check src tests
	uv run ruff format --check src tests

fmt: ## Formate le code
	uv run ruff format src tests
	uv run ruff check --fix src tests

diagram: ## Regénère le modèle de données (nécessite plantuml)
	plantuml -tpng -o img docs/data-model.puml
	plantuml -tsvg -o img docs/data-model.puml

logs: ## Suit les logs des conteneurs
	docker compose logs -f

reset: ## ⚠ Détruit conteneurs, volumes et zone de travail (source intacte)
	@read -p "Supprimer les conteneurs et TOUTES les données locales ? [y/N] " ok; \
	 [ "$$ok" = "y" ] || { echo "Annulé."; exit 1; }
	docker compose down -v
	rm -rf data logs
	@echo "→ Réinitialisé. `make demo` repart de zéro."
