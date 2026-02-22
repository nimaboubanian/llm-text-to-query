-- TPC-H Q11: Important Stock Identification Query (Q11)
-- Substitution parameter: NATION in [N_NAME], FRACTION in [0.0001 / SF] (validation uses NATION = 'GERMANY', FRACTION = 0.0001)

SELECT
  ps_partkey,
  SUM(ps_supplycost * ps_availqty) AS value
FROM
  partsupp,
  supplier,
  nation
WHERE
  ps_suppkey = s_suppkey
  AND s_nationkey = n_nationkey
  AND n_name = 'GERMANY'
GROUP BY
  ps_partkey
HAVING
  SUM(ps_supplycost * ps_availqty) > (
    SELECT
      SUM(ps_supplycost * ps_availqty) * 0.0001
    FROM
      partsupp,
      supplier,
      nation
    WHERE
      ps_suppkey = s_suppkey
      AND s_nationkey = n_nationkey
      AND n_name = 'GERMANY'
  )
ORDER BY
  value DESC;
