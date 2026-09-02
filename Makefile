# EDS CHU — points d'entrée du projet.
# `make demo` part de zéro et amène jusqu'aux dashboards.

.DEFAULT_GOAL := help
SHELL := /bin/bash

# Toutes les commandes lisent .env ; on le crée à partir de l'exemple si besoin.
ENV_FILE := .env

.PHONY: help env up down pipeline provision demo test test-e2e lint fmt reset logs status quality diagram \
        dbt-build dbt-test dbt-docs image image-push \
        cloud-bootstrap cloud-plan cloud-apply cloud-seed cloud-provision cloud-run \
        cloud-check cloud-status cloud-logs cloud-stop cloud-start cloud-destroy

help: ## Affiche cette aide
	@# Le motif accepte les chiffres : sans quoi une cible comme `test-e2e`
	@# resterait invisible dans l'aide tout en étant documentée ailleurs.
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# Valeur d'exemple du sel, refusée au démarrage car publique.
PLACEHOLDER_SALT := remplace-moi-par-openssl-rand-hex-32
# Les six secrets à tirer au hasard à la création du .env.
SECRET_VARS := CLICKHOUSE_ETL_PASSWORD CLICKHOUSE_PILOTAGE_PASSWORD \
               CLICKHOUSE_RECHERCHE_PASSWORD MB_ADMIN_PASSWORD \
               MB_PILOTAGE_PASSWORD MB_RECHERCHE_PASSWORD

env: ## Crée .env si besoin, avec sel et mots de passe tirés au hasard
	@# Le préfixe et le suffixe fixes ne sont pas décoratifs : Metabase exige
	@# majuscule, minuscule, chiffre et caractère spécial, ce qu'un hexadécimal
	@# seul ne garantit pas.
	@if [ ! -f $(ENV_FILE) ]; then \
	    cp .env.example $(ENV_FILE); \
	    for VAR in $(SECRET_VARS); do \
	        MDP="Chu-$$(openssl rand -hex 12)-7!"; \
	        sed -i.bak "s|^$$VAR=.*|$$VAR=$$MDP|" $(ENV_FILE); \
	    done; \
	    rm -f $(ENV_FILE).bak; \
	    echo "→ .env créé depuis .env.example, mots de passe tirés au hasard."; \
	 fi
	@# On traite aussi le cas d'un .env recopié à la main. Le sel est corrigé
	@# d'office — sans quoi le pipeline refuserait de démarrer. Les mots de passe,
	@# eux, sont seulement signalés : celui de ClickHouse est lu par Docker à la
	@# création du conteneur, le réécrire ici casserait l'authentification d'un
	@# entrepôt déjà démarré. `eds` nomme les variables restantes à chaque appel.
	@if grep -q "^EDS_SALT=$(PLACEHOLDER_SALT)$$" $(ENV_FILE); then \
	    SALT=$$(openssl rand -hex 32); \
	    sed -i.bak "s|^EDS_SALT=.*|EDS_SALT=$$SALT|" $(ENV_FILE) && rm -f $(ENV_FILE).bak; \
	    echo "→ Sel de pseudonymisation généré aléatoirement."; \
	 fi
	@# Le motif ne vise que les affectations : le mot « change_me » apparaît aussi
	@# dans les commentaires du modèle, il ne doit pas déclencher l'alerte.
	@# Guillemets simples autour des messages : entre guillemets doubles, bash
	@# interpréterait les accents graves comme une substitution de commande.
	@if grep -qE '^[A-Z_]+=.*change_me' $(ENV_FILE); then \
	    echo '  ⚠ Des mots de passe d'"'"'exemple subsistent dans .env (marque « change_me »).'; \
	    echo '    Remplacez-les, ou supprimez .env et relancez `make env`.'; \
	 fi

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

dbt-build: ## Reconstruit et teste silver + gold (dbt), sans réingérer
	uv run eds run --rebuild

dbt-test: ## Rejoue les seuls tests dbt sur l'entrepôt en place
	set -a && . ./$(ENV_FILE) && set +a && uv run dbt test --project-dir dbt --profiles-dir dbt

dbt-docs: ## Génère la documentation dbt (graphe des modèles)
	set -a && . ./$(ENV_FILE) && set +a && uv run eds publish-dbt-docs

image: ## Construit l'image du pipeline en local
	docker build -t eds-chu:local .

# ⚠ `--platform linux/amd64` : Container Apps n'exécute pas d'arm64, et un Mac Apple
# Silicon en produirait par défaut. Le job échouerait au démarrage, sans message clair.
image-push: ## Construit en amd64 et publie l'image du pipeline
	docker buildx build --platform linux/amd64 -t $(IMAGE):latest -t $(IMAGE):$$(git rev-parse --short HEAD) --push .
	@echo "→ Publiée : $(IMAGE):$$(git rev-parse --short HEAD)"

# ─────────────────────────────────────────────────────────────────────────────
#  Déploiement Azure — cf. terraform/README.md
# ─────────────────────────────────────────────────────────────────────────────
# Registre public : les jobs Azure tirent l'image sans aucun identifiant.
IMAGE := louis336/eds-chu
TF := terraform -chdir=terraform
# Le groupe et les noms sont lus dans les sorties Terraform : ils ne sont écrits
# qu'à un seul endroit, et ne peuvent pas devenir faux ici.
RG = $(shell $(TF) output -raw nom_groupe 2>/dev/null)

cloud-bootstrap: ## Enregistre les fournisseurs et crée le backend d'état (une fois)
	@bash scripts/cloud-bootstrap.sh

cloud-plan: ## terraform plan
	$(TF) plan

cloud-apply: ## terraform apply — crée ou met à jour l'infrastructure
	$(TF) apply

cloud-seed: ## Téléverse source-filestorage/ vers le dépôt du CHU (conteneur filestorage)
	@ACC=$$($(TF) output -raw compte_stockage); \
	 echo "→ Dépôt du CHU vers $$ACC/filestorage…"; \
	 for EXT in csv json parquet; do \
	   az storage blob upload-batch --account-name $$ACC --auth-mode login \
	     -d filestorage -s source-filestorage --overwrite --pattern "*.$$EXT" -o none; \
	 done; \
	 echo "→ $$(az storage blob list --account-name $$ACC --auth-mode login -c filestorage --query 'length(@)' -o tsv) fichiers déposés."

cloud-provision: ## Déclenche job-eds-provision (entrepôt, Metabase, documentation dbt)
	az containerapp job start -n job-eds-provision -g $(RG) -o none
	@echo "→ Lancé. Suivi : make cloud-status"

cloud-run: ## Déclenche job-eds-pipeline immédiatement
	az containerapp job start -n job-eds-pipeline -g $(RG) -o none
	@echo "→ Lancé. Suivi : make cloud-status"

cloud-check: ## Déclenche job-eds-controle (preuve du cloisonnement)
	az containerapp job start -n job-eds-controle -g $(RG) -o none

cloud-status: ## État de la VM et des dernières exécutions des jobs
	@echo "── VM ──"
	@az vm get-instance-view -g $(RG) -n $$($(TF) output -raw nom_vm) \
	   --query "instanceView.statuses[?starts_with(code,'PowerState')].displayStatus" -o tsv
	@echo "── Jobs ──"
	@for J in job-eds-pipeline job-eds-provision job-eds-controle; do \
	   az containerapp job execution list -n $$J -g $(RG) \
	     --query "sort_by([].{job:'$$J',debut:properties.startTime,statut:properties.status}, &debut)[-3:]" \
	     -o table 2>/dev/null | tail -4; \
	 done

cloud-logs: ## Journaux de la dernière exécution du pipeline
	@az containerapp job logs show -n job-eds-pipeline -g $(RG) --container eds --tail 200 2>/dev/null \
	 || echo "Aucune exécution récente. Voir Log Analytics (requête dans les sorties Terraform)."

cloud-stop: ## Désalloue la VM — la facture tombe à ~5 €/mois
	az vm deallocate -g $(RG) -n $$($(TF) output -raw nom_vm) -o none
	@echo '→ VM désallouée. `make cloud-start` la remonte, pile comprise.'

cloud-start: ## Rallume la VM ; la pile remonte seule
	az vm start -g $(RG) -n $$($(TF) output -raw nom_vm) -o none
	@echo "→ VM démarrée. Comptez deux minutes avant que Metabase réponde."

cloud-destroy: ## ⚠ Détruit toute l'infrastructure Azure
	$(TF) destroy

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
	@# Guillemets simples : entre guillemets doubles, bash interpréterait les
	@# accents graves comme une substitution de commande et relancerait la démo.
	@echo '→ Réinitialisé. Lancez `make demo` pour repartir de zéro.'
