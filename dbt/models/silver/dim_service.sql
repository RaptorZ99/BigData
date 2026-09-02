{{ config(order_by='service_code') }}
-- Dimension conformée service hospitalier (référentiel du CHU), complétée depuis le
-- 29 août 2026 par sa description : catégorie, capacité en lits, pôle.
--
-- ═══════════════════════════════════════════════════════════════════════════
--  Le référentiel de description est incomplet : NEURO n'y figure pas.
--
--  Un service non décrit reste un service. Ses séjours, ses actes et sa DMS existent,
--  et le retirer casserait tous les indicateurs historiques — c'est la non-régression
--  exigée. La jointure est donc EXTERNE, et l'absence est traitée en trois temps :
--
--    * `categorie` et `pole` reçoivent le libellé explicite « non renseigne », qui se
--      regroupe et s'affiche comme n'importe quelle valeur — un NULL disparaîtrait des
--      graphiques sans laisser de trace ;
--    * `capacite_lits` reste NULL : on ne fabrique pas un nombre de lits. La densité
--      d'actes par lit sera NULL pour ce service, ni 0 ni infinie ;
--    * `est_decrit` porte le fait, et la règle Q9 le compte au rapport qualité.
--
--  ClickHouse remplit les colonnes non appariées d'une jointure externe avec la valeur
--  par défaut du type (chaîne vide), pas avec NULL : le test d'appariement porte sur
--  `service_code`, jamais sur un `ifNull`.
-- ═══════════════════════════════════════════════════════════════════════════
WITH description AS
(
    -- Dernière version déposée de chaque description.
    SELECT
        service_code,
        argMax(categorie, _ingest_date)     AS categorie,
        argMax(capacite_lits, _ingest_date) AS capacite_lits,
        argMax(pole, _ingest_date)          AS pole
    FROM {{ source('bronze', 'description_service') }}
    GROUP BY service_code
)
SELECT
    s.service_code                                              AS service_code,
    s.service_label                                             AS service_label,
    if(d.service_code = '', 'non renseigne', d.categorie)       AS categorie,
    if(d.service_code = '', 'non renseigne', d.pole)            AS pole,
    -- Zéro lit n'est pas une capacité : ramené à NULL comme une valeur absente.
    nullIf(d.capacite_lits, 0)                                  AS capacite_lits,
    CAST(d.service_code != '' AS Bool)                          AS est_decrit,
    s.source_file                                               AS _source_file,
    s.last_ingest_date                                          AS _ingest_date,
    now()                                                       AS _built_at
FROM
(
    SELECT
        service_code,
        argMax(service_label, _ingest_date) AS service_label,
        argMax(_source_file, _ingest_date)  AS source_file,
        max(_ingest_date)                   AS last_ingest_date
    FROM {{ source('bronze', 'services') }}
    GROUP BY service_code
) AS s
LEFT JOIN description AS d USING (service_code)
