{{ config(order_by='(service_code, acte_ts)') }}
-- Étoile 4 — fact_acte, grain : un acte médical réalisé pendant un séjour.
-- Dimensions directes : dim_service (service_code propagé depuis le séjour),
-- dim_ccam (code_ccam). `stay_id` reste en dimension dégénérée.
--
-- ═══════════════════════════════════════════════════════════════════════════
--  Le service est porté par le séjour, pas par l'acte.
--
--  Le sujet demande « actes par service » sans relier deux tables de faits. La réponse
--  est celle des deux autres faits secondaires : le service est résolu ICI, au build,
--  depuis le référentiel de tous les séjours déposés, et rangé sur le fait. Côté gold,
--  « actes par service » devient un simple GROUP BY sur cette table — aucune jointure
--  fact_acte ⋈ fact_sejour n'existe nulle part.
-- ═══════════════════════════════════════════════════════════════════════════
--
-- Minimisation RGPD : `patient_pseudo` n'est pas propagé — aucun indicateur d'actes
-- ne compte des patients. La donnée ne descend donc pas jusqu'ici.
--
-- Le montant est une MESURE du fait : c'est le tarif du référentiel au moment du build,
-- soit ce que la T2A facture. Le garder sur le fait rend la somme additive et directe ;
-- `dim_ccam` reste la source pour le libellé et le tarif courant.
--
-- Règles qualité :
--   C3   séjour absent du dépôt          → REJET (voir actes_rejets) — attendu à 0
--   Q6   code CCAM absent du référentiel → FLAG, montant NULL — attendu à 0
--   Q10  acte hors des bornes du séjour  → FLAG, sur les seuls séjours cohérents
SELECT
    a.stay_id                                   AS stay_id,
    s.service_code                              AS service_code,
    a.code_ccam                                 AS code_ccam,
    a.acte_ts                                   AS acte_ts,
    toDate(a.acte_ts)                           AS acte_date,

    -- Mesure : NULL si le code est inconnu ou son tarif absent — jamais 0, qui
    -- passerait pour un acte gratuit dans une somme.
    c.tarif_euros                               AS montant_euros,

    CAST(c.code_ccam = '' AS Bool)              AS is_code_inconnu,
    -- Q10 : un acte avant l'admission ou après la sortie. Le contrôle ne se prononce
    -- que sur les séjours temporellement cohérents — sur les autres, c'est la date de
    -- sortie qui est fausse, et la comparaison n'aurait aucun sens.
    ifNull(
        s.est_coherent AND (a.acte_ts < s.admission_ts OR a.acte_ts > s.discharge_ts),
        false
    )                                           AS is_hors_sejour,

    a.source_file                               AS _source_file,
    a.last_ingest_date                          AS _ingest_date,
    now()                                       AS _built_at
FROM {{ ref('stg_actes') }} AS a
-- Jointure interne : un acte dont le séjour est absent du dépôt n'a pas de service
-- résoluble. Il part dans actes_rejets avec son motif (contrôle C3).
INNER JOIN {{ ref('stg_sejours') }} AS s USING (stay_id)
LEFT JOIN {{ ref('dim_ccam') }} AS c USING (code_ccam)
