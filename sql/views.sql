CREATE OR REPLACE VIEW prices.price_history AS
WITH base AS (
 SELECT product_id,city,argMinIf(value,observation_date,value IS NOT NULL) AS base_price,
 minIf(observation_date,value IS NOT NULL) AS base_date
 FROM prices.observations WHERE metric='price' GROUP BY product_id,city
), national AS (
 SELECT observation_date,product_id,value AS national_price FROM prices.observations WHERE metric='price' AND city='Казахстан'
), series AS (
 SELECT *,lagInFrame(value,1,NULL) OVER w AS previous_price,
 lagInFrame(toNullable(observation_date),1,NULL) OVER w AS previous_date
 FROM prices.observations WHERE metric='price'
 WINDOW w AS (PARTITION BY product_id,city ORDER BY observation_date ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
)
SELECT s.observation_date AS observation_date,s.city AS city,s.product_id AS product_id,s.product AS product,s.product_group AS product_group,s.unit AS unit,s.value AS price,
 s.value_status,s.raw_label,s.raw_value,s.source_url,s.source_file,s.source_sheet,s.source_row,s.source_column,
 n.national_price,b.base_date,b.base_price,
 if(b.base_price>0,s.value/b.base_price*100,NULL) AS price_index,
 if(n.national_price>0,(s.value/n.national_price-1)*100,NULL) AS premium_pct,
 if(previous_price>0 AND dateDiff('day',previous_date,s.observation_date) BETWEEN 1 AND 10,(s.value/previous_price-1)*100,NULL) AS price_change_week_pct,
 toYear(s.observation_date) AS year,toMonth(s.observation_date) AS month,
 formatDateTime(s.observation_date,'%m') AS month_label,
 if(s.city='Казахстан','Официальная цена по стране','Средняя цена по городу') AS geography_type
FROM series s LEFT JOIN national n USING (observation_date,product_id) LEFT JOIN base b USING (product_id,city);

CREATE OR REPLACE VIEW prices.prices_latest AS
SELECT * FROM prices.price_history WHERE observation_date=(SELECT max(observation_date) FROM prices.observations WHERE metric='price');

CREATE OR REPLACE VIEW prices.index_history AS
SELECT observation_date,city,product_id,product,product_group,metric,value AS index_value,value-100 AS change_pct,
 multiIf(metric='wow','За неделю',metric='yoy','За год',metric='ytd','С начала года',metric='mtd','С начала месяца',metric) AS comparison,
 value_status,comparison_label,source_url FROM prices.observations WHERE metric!='price';

CREATE OR REPLACE VIEW prices.indices_latest AS
SELECT * FROM prices.index_history WHERE observation_date=(SELECT max(observation_date) FROM prices.observations WHERE metric='price');

CREATE OR REPLACE VIEW prices.indices_movers_latest AS
SELECT *, multiIf(
 startsWith(product,'Молоко ('), 'Молоко 2,2–6%',
 startsWith(product,'Мясо кур ('), 'Куриные части',
 startsWith(product,'Рыба свежая'), 'Рыба',
 startsWith(product,'Конина,'), 'Конина',
 startsWith(product,'Баранина,'), 'Баранина',
 startsWith(product,'Хлеб пшеничный'), 'Хлеб, 1 сорт',
 product) AS product_short
FROM prices.indices_latest
WHERE city='Казахстан' AND metric='wow' AND product_id!='all_food'
ORDER BY change_pct DESC, product
LIMIT 10;

CREATE OR REPLACE VIEW prices.basket_history AS
WITH basket AS (
 SELECT observation_date,city,countIf(value IS NOT NULL) AS products_available,11 AS products_required,
 if(countIf(value IS NOT NULL)=11,sum(value),NULL) AS basket_cost,
 countIf(value IS NOT NULL)/11*100 AS coverage_pct
 FROM prices.observations WHERE metric='price' AND product_id IN
 ('flour','bread','rice','buckwheat','sunflower_oil','potato','carrot','onion','cabbage','sugar','eggs')
 GROUP BY observation_date,city
), b AS (
 SELECT city,argMinIf(basket_cost,observation_date,basket_cost IS NOT NULL) AS first_cost FROM basket GROUP BY city
), n AS (SELECT observation_date,basket_cost AS national_cost FROM basket WHERE city='Казахстан')
SELECT a.observation_date AS observation_date,a.city AS city,a.products_available AS products_available,
 a.products_required AS products_required,a.basket_cost AS basket_cost,a.coverage_pct AS coverage_pct,
 b.first_cost AS first_cost,if(first_cost>0,basket_cost/first_cost*100,NULL) AS basket_index,
 n.national_cost,if(national_cost>0,(basket_cost/national_cost-1)*100,NULL) AS basket_premium_pct
FROM basket a LEFT JOIN b USING city LEFT JOIN n USING observation_date;

CREATE OR REPLACE VIEW prices.basket_latest AS
SELECT * FROM prices.basket_history WHERE observation_date=(SELECT max(observation_date) FROM prices.observations);

CREATE OR REPLACE VIEW prices.dispersion AS
SELECT observation_date,product_id,any(product) AS product,any(product_group) AS product_group,any(unit) AS unit,
 min(value) AS min_price,quantileExact(0.5)(value) AS median_price,max(value) AS max_price,avg(value) AS unweighted_mean,
 argMin(city,ifNull(value,1e20)) AS cheapest_city,argMax(city,ifNull(value,-1)) AS expensive_city,
 countIf(value IS NOT NULL) AS cities_available,(max(value)/min(value)-1)*100 AS spread_pct
FROM prices.observations WHERE metric='price' AND city!='Казахстан' AND value IS NOT NULL
GROUP BY observation_date,product_id;

CREATE OR REPLACE VIEW prices.dispersion_latest AS
SELECT * FROM prices.dispersion WHERE observation_date=(SELECT max(observation_date) FROM prices.observations);

CREATE OR REPLACE VIEW prices.coverage AS
SELECT observation_date,metric,count() AS expected_cells,countIf(value IS NOT NULL) AS observed_cells,
 countIf(value IS NULL) AS missing_cells,countIf(value IS NOT NULL)/count()*100 AS coverage_pct,
 uniqExactIf(product_id,product_id!='all_food') AS products,uniqExactIf(city,city!='Казахстан') AS cities
FROM prices.observations GROUP BY observation_date,metric;
