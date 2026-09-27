{#- Rows where this column is earlier than another column, e.g. closed_at < created_at. -#}
{% test not_before(model, column_name, other_column) %}

select {{ column_name }}, {{ other_column }}
from {{ model }}
where {{ column_name }} < {{ other_column }}

{% endtest %}
