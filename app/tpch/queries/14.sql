-- TPC-H Q14: Promotion Effect Query (Q14)
-- Substitution parameter: DATE (first day of a month from a random year in [1993..1997]) (validation uses DATE = 1995-09-01)

SELECT
  100.00 * SUM(CASE
    WHEN p_type LIKE 'PROMO%'
      THEN l_extendedprice * (1 - l_discount)
    ELSE 0
  END) / SUM(l_extendedprice * (1 - l_discount)) AS promo_revenue
FROM
  lineitem,
  part
WHERE
  l_partkey = p_partkey
  AND l_shipdate >= DATE '1995-09-01'
  AND l_shipdate <  DATE '1995-09-01' + INTERVAL '1' MONTH;
