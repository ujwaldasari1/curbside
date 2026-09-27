{#- Timestamps later than tomorrow (NYC 311 has published closed dates as late as 2033). -#}
{% test not_in_future(model, column_name) %}

select {{ column_name }}
from {{ model }}
where {{ column_name }} > now() + interval '1 day'

{% endtest %}
