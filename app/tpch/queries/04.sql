-- TPC-H Q4: Order Priority Checking Query (Q4)
-- Substitution parameter: DATE in [1993-01..1997-10] (validation uses DATE = 1993-07-01)

SELECT
  o_orderpriority,
  COUNT(*) AS order_count
FROM
  orders
WHERE
  o_orderdate >= DATE '1993-07-01'
  AND o_orderdate < DATE '1993-07-01' + INTERVAL '3' MONTH
  AND EXISTS (
    SELECT
      *
    FROM
      lineitem
    WHERE
      l_orderkey = o_orderkey
      AND l_commitdate < l_receiptdate
  )
GROUP BY
  o_orderpriority
ORDER BY
  o_orderpriority;
