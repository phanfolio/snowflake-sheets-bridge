-- Every 200th customer (a deterministic sample). Primary key: CUSTKEY. Foreign key: NATIONKEY -> nation.
SELECT c_custkey AS custkey, c_name AS customer_name, c_nationkey AS nationkey,
       c_mktsegment AS market_segment, c_acctbal AS customer_balance
FROM snowflake_sample_data.tpch_sf1.customer
WHERE MOD(c_custkey, 200) = 0
ORDER BY 1
