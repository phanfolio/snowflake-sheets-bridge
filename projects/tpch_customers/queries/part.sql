-- Only the parts that the sampled line items reference, so no line item points at a missing part.
-- Primary key: PARTKEY.
SELECT p_partkey AS partkey, p_name AS part_name, p_brand AS brand, p_type AS part_type,
       p_size AS part_size, p_retailprice AS retail_price
FROM snowflake_sample_data.tpch_sf1.part
WHERE p_partkey IN (
    SELECT l.l_partkey
    FROM snowflake_sample_data.tpch_sf1.lineitem AS l
    JOIN snowflake_sample_data.tpch_sf1.orders   AS o ON o.o_orderkey = l.l_orderkey
    WHERE MOD(o.o_custkey, 200) = 0)
ORDER BY 1
