{#- NYC borough name -> standard borough code (1 Manhattan ... 5 Staten Island).
    Case-insensitive; unknown names return null. `boro_cd` = borough_code * 100 + district. -#}
{% macro borough_code(expr) -%}
    case upper(trim({{ expr }}))
        when 'MANHATTAN' then 1
        when 'BRONX' then 2
        when 'BROOKLYN' then 3
        when 'QUEENS' then 4
        when 'STATEN ISLAND' then 5
    end
{%- endmacro %}
