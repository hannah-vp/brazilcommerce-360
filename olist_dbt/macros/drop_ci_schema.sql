{#
    Drops a CI schema after a pull-request build.

    Each PR builds into its own schema (ci_pr_<number>) so concurrent runs cannot
    collide. Without this cleanup those schemas would accumulate indefinitely and
    carry storage cost.

    Called from the CI workflow:
        dbt run-operation drop_ci_schema --args "{schema_name: ci_pr_42}"
#}

{% macro drop_ci_schema(schema_name) %}

    {% if not schema_name.startswith('ci_') %}
        {{ exceptions.raise_compiler_error(
            "drop_ci_schema refuses to drop '" ~ schema_name ~
            "'. Only schemas prefixed with ci_ may be dropped."
        ) }}
    {% endif %}

    {% set sql %}
        drop schema if exists {{ target.database }}.{{ schema_name }} cascade
    {% endset %}

    {{ log("Dropping " ~ target.database ~ "." ~ schema_name, info=True) }}
    {% do run_query(sql) %}

{% endmacro %}
