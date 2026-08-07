-- TPC-H Q15: Top Supplier Query (Q15)
-- Substitution parameter: DATE (first day of a month in [1993..1997]) (validation uses DATE = 1996-01-01)
-- Rewritten as a single-statement CTE (standard TPC-H Q15 uses CREATE VIEW)

WITH revenue0 (supplier_no, total_revenue) AS (
  SELECT
    l_suppkey,
    SUM(l_extendedprice * (1 - l_discount))
  FROM
    lineitem
  WHERE
    l_shipdate >= DATE '1996-01-01'
    AND l_shipdate < DATE '1996-01-01' + INTERVAL '3' MONTH
  GROUP BY
    l_suppkey
)
SELECT
  s_suppkey,
  s_name,
  s_address,
  s_phone,
  total_revenue
FROM
  supplier,
  revenue0
WHERE
  s_suppkey = supplier_no
  AND total_revenue = (
    SELECT
      MAX(total_revenue)
    FROM
      revenue0
  )
ORDER BY
  s_suppkey;
