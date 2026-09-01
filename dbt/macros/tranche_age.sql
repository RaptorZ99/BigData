{#
    Tranches d'âge de dix ans, calculées depuis la seule année de naissance —
    la date complète n'existe nulle part dans l'entrepôt (généralisation RGPD à
    la collecte). L'âge est donc celui atteint dans l'année, jamais au jour près :
    c'est précisément l'effet recherché.

    Écrit une fois ici, utilisé par les trois modèles démographiques : le jour où
    la granularité change, elle change partout.
#}
{% macro tranche_age_debut(birth_year) -%}
    intDiv(toYear(today()) - {{ birth_year }}, 10) * 10
{%- endmacro %}

{% macro tranche_age_libelle(birth_year) -%}
    concat(
        toString({{ tranche_age_debut(birth_year) }}),
        '-',
        toString({{ tranche_age_debut(birth_year) }} + 9)
    )
{%- endmacro %}
