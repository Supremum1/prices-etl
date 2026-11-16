{% set selected = filter_values("product", remove_filter=True) %}
{% if not selected %}
{% set selected = ['Гречневая крупа', 'Капуста белокочанная', 'Картофель', 'Лук репчатый', 'Масло подсолнечное', 'Морковь', 'Мука пшеничная, 1 сорт', 'Рис шлифованный', 'Сахар-песок', 'Хлеб пшеничный, 1 сорт', 'Яйца, I категории'] %}
{% endif %}
{% set required = selected | length %}
WITH basket AS (
 SELECT observation_date,city,countIf(value IS NOT NULL) AS products_available,{{ required }} AS products_required,
 if(countIf(value IS NOT NULL)= {{ required }},sum(value),NULL) AS basket_cost,
 countIf(value IS NOT NULL)/{{ required }}*100 AS coverage_pct
 FROM prices.observations WHERE metric='price' AND product IN {{ selected | where_in }}
 GROUP BY observation_date,city
), b AS (
 SELECT city,argMinIf(basket_cost,observation_date,basket_cost IS NOT NULL) AS first_cost FROM basket GROUP BY city
), n AS (SELECT observation_date,basket_cost AS national_cost FROM basket WHERE city='Казахстан')
SELECT a.observation_date AS observation_date,a.city AS city,a.products_available AS products_available,
 a.products_required AS products_required,'' AS product,a.basket_cost AS basket_cost,a.coverage_pct AS coverage_pct,
 b.first_cost AS first_cost,if(first_cost>0,basket_cost/first_cost*100,NULL) AS basket_index,
 n.national_cost,if(national_cost>0,(basket_cost/national_cost-1)*100,NULL) AS basket_premium_pct
FROM basket a LEFT JOIN b USING city LEFT JOIN n USING observation_date
