-- Orders of the sampled customers. Primary key: ORDERKEY. Foreign key: CUSTKEY -> customer.
SELECT o_orderkey AS orderkey, o_custkey AS custkey, o_orderdate AS order_date,
       o_orderstatus AS order_status, o_orderpriority AS order_priority, o_totalprice AS total_price
FROM snowflake_sample_data.tpch_sf1.orders
WHERE MOD(o_custkey, 200) = 0
ORDER BY 1
