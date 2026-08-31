# EDS CHU — Entrepôt de Données de Santé

Pipeline médaillon complet : dépôts quotidiens hétérogènes du CHU → entrepôt ClickHouse
→ dashboards Metabase cloisonnés, avec pseudonymisation dès l'entrée du lake.

*(Documentation complète en cours de rédaction — cf. `PLAN.md`.)*

## Démarrage rapide

```bash
cp .env.example .env
make demo
```
