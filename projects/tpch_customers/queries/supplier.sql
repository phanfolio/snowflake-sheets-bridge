-- Only the suppliers that the sampled line items reference. Primary key: SUPPKEY. Foreign key: NATIONKEY -> nation.
SELECT s_suppkey AS suppkey, s_name AS supplier_name, s_nationkey AS nationkey, s_acctbal AS supplier_balance
FROM snowflake_sample_data.tpch_sf1.supplier
WHERE s_suppkey IN (
    SELECT l.l_suppkey
    FROM snowflake_sample_data.tpch_sf1.lineitem AS l
    JOIN snowflake_sample_data.tpch_sf1.orders   AS o ON o.o_orderkey = l.l_orderkey
    WHERE MOD(o.o_custkey, 200) = 0)
ORDER BY 1
