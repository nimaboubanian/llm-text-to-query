-- TPC-H Q19: Discounted Revenue Query (Q19)
-- Substitution parameters: QUANTITY1 = 1, QUANTITY2 = 10, QUANTITY3 = 20, BRAND1 = 'Brand#12', BRAND2 = 'Brand#23', BRAND3 = 'Brand#34' (validation uses these specific values)
--
-- DEVIATION FROM SPEC (deliberate, do not "fix" back): the official TPC-H text
-- reads l_shipmode IN ('AIR', 'AIR REG'). No such mode exists — dbgen emits
-- 'REG AIR' — so the spec's literal matches 0 rows and Q19 silently degrades to
-- AIR-only. Corrected to 'REG AIR' so the query means what the question asks.
-- Consequence: revenue is 6388788.1139 (254 rows), not the published SF1
-- validation answer 3083843.0578 (121 rows). Q19 is no longer comparable to
-- official TPC-H results by design.

SELECT
  SUM(l_extendedprice * (1 - l_discount)) AS revenue
FROM
  lineitem,
  part
WHERE
  (
    p_partkey = l_partkey
    AND p_brand = 'Brand#12'
    AND p_container IN ('SM CASE', 'SM BOX', 'SM PACK', 'SM PKG')
    AND l_quantity >= 1
    AND l_quantity <= 1 + 10
    AND p_size BETWEEN 1 AND 5
    AND l_shipmode IN ('AIR', 'REG AIR')
    AND l_shipinstruct = 'DELIVER IN PERSON'
  )
  OR
  (
    p_partkey = l_partkey
    AND p_brand = 'Brand#23'
    AND p_container IN ('MED BAG', 'MED BOX', 'MED PKG', 'MED PACK')
    AND l_quantity >= 10
    AND l_quantity <= 10 + 10
    AND p_size BETWEEN 1 AND 10
    AND l_shipmode IN ('AIR', 'REG AIR')
    AND l_shipinstruct = 'DELIVER IN PERSON'
  )
  OR
  (
    p_partkey = l_partkey
    AND p_brand = 'Brand#34'
    AND p_container IN ('LG CASE', 'LG BOX', 'LG PACK', 'LG PKG')
    AND l_quantity >= 20
    AND l_quantity <= 20 + 10
    AND p_size BETWEEN 1 AND 15
    AND l_shipmode IN ('AIR', 'REG AIR')
    AND l_shipinstruct = 'DELIVER IN PERSON'
  );
