-- TPC-H Q13: Customer Distribution Query (Q13)
-- Substitution parameters: WORD1 in ['special', 'pending', 'unusual', 'express'], WORD2 in ['packages', 'requests', 'accounts', 'deposits'] (validation uses WORD1 = 'special', WORD2 = 'requests')

SELECT
  c_count,
  COUNT(*) AS custdist
FROM (
  SELECT
    c_custkey,
    COUNT(o_orderkey) AS c_count
  FROM
    customer LEFT OUTER JOIN orders ON
      c_custkey = o_custkey
      AND o_comment NOT LIKE '%special%requests%'
  GROUP BY
    c_custkey
) AS c_orders
GROUP BY
  c_count
ORDER BY
  custdist DESC,
  c_count DESC;
