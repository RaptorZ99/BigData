# Image du pipeline EDS — utilisée par les jobs Container Apps.
#
# Elle embarque l'orchestrateur, les scripts SQL de bronze et le projet dbt : le
# job n'a pas de dépôt Git à cloner, et la version exécutée est exactement celle
# que le tag de l'image désigne.
#
# Python 3.13 et non 3.14 : dbt-core 1.11 ne démarre pas sur 3.14 (mashumaro,
# UnserializableField sur JSONObjectSchema.schema). Cf. docs/PLAN-CLOUD.md §5.6.

FROM python:3.13-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.9.9 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Les dépendances d'abord, le code ensuite : une modification de `src/` ne
# réinstalle pas l'environnement. `--frozen` garantit que l'image utilise
# exactement les versions du lock, y compris celles de dbt.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --extra azure --extra dbt

COPY src/ src/
COPY sql/ sql/
COPY dbt/ dbt/
RUN uv sync --frozen --no-dev --extra azure --extra dbt


FROM python:3.13-slim

# Un job n'a aucune raison de tourner en root.
RUN useradd --create-home --uid 10001 eds

COPY --from=build --chown=eds:eds /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # dbt écrit ses journaux et son manifeste : /app est en lecture seule pour
    # l'utilisateur applicatif dans certaines configurations, /tmp ne l'est jamais.
    DBT_LOG_PATH=/tmp/dbt-logs \
    DBT_TARGET_PATH=/tmp/dbt-target

USER eds
WORKDIR /app

# Point d'entrée `eds` : la commande du job se lit alors `["run"]`,
# `["provision-warehouse"]`, `["check-cloisonnement"]`.
ENTRYPOINT ["eds"]
CMD ["--help"]
