-- Line items of the sampled orders. Primary key: (ORDERKEY, LINENUMBER), a composite key.
-- Foreign keys: ORDERKEY -> orders, PARTKEY -> part, SUPPKEY -> supplier.
SELECT l.l_orderkey AS orderkey, l.l_linenumber AS linenumber, l.l_partkey AS partkey, l.l_suppkey AS suppkey,
       l.l_quantity AS quantity, l.l_extendedprice AS extended_price, l.l_discount AS discount,
       l.l_shipdate AS ship_date, l.l_returnflag AS return_flag
FROM snowflake_sample_data.tpch_sf1.lineitem AS l
JOIN snowflake_sample_data.tpch_sf1.orders   AS o ON o.o_orderkey = l.l_orderkey
WHERE MOD(o.o_custkey, 200) = 0
ORDER BY 1, 2
