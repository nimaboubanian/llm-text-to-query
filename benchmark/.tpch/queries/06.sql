-- TPC-H Q6: Forecasting Revenue Change Query (Q6)
-- Substitution parameters: DATE in [1993..1997], DISCOUNT in [0.02..0.09], QUANTITY in [24..25] (validation uses DATE = 1994-01-01, DISCOUNT = 0.06, QUANTITY = 24)

SELECT
  SUM(l_extendedprice * l_discount) AS revenue
FROM
  lineitem
WHERE
  l_shipdate >= DATE '1994-01-01'
  AND l_shipdate <  DATE '1994-01-01' + INTERVAL '1' YEAR
  AND l_discount BETWEEN (0.06 - 0.01) AND (0.06 + 0.01)
  AND l_quantity < 24;
