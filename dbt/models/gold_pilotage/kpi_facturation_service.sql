{{ config(order_by='rang') }}
-- KPI évolution 5 — Montant facturé par service (T2A : somme des tarifs des actes).
--
-- Grain : le service. Le montant est la somme des tarifs CCAM portés par `fact_acte`
-- — une mesure additive du fait, pas un recalcul depuis la nomenclature. Agrégation
-- reprise de `int_actes_service`. Le total de l'établissement est publié dans
-- `kpi_synthese`, repris de cette table.
--
-- `rang` classe les services du plus au moins facturé ; clé de tri physique de la table.
SELECT
    service_code,
    service_label,
    nb_actes,
    montant_facture_euros,
    row_number() OVER (ORDER BY montant_facture_euros DESC, service_code) AS rang
FROM {{ ref('int_actes_service') }}
