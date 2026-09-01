{#
    Sans cette surcharge, dbt nomme la base cible `<schéma du profil>_<schéma du modèle>`
    et créerait `eds_silver_eds_gold_pilotage`. Ici le schéma déclaré dans
    `dbt_project.yml` EST la base ClickHouse : on le rend tel quel.

    Conséquence assumée : deux exécutions concurrentes sur le même serveur écriraient
    dans les mêmes tables. C'est déjà le cas du pipeline actuel, et c'est voulu —
    l'entrepôt a une seule vérité.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
