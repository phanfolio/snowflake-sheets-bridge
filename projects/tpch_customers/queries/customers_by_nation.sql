-- Customers and account balances by nation and market segment: 25 nations x 5 segments = 125 rows.
SELECT
    n.n_name           AS nation,            -- VARCHAR
    c.c_mktsegment     AS market_segment,
    COUNT(*)           AS customers,         -- integer NUMBER
    SUM(c.c_acctbal)   AS total_balance,     -- NUMBER(p,2)
    AVG(c.c_acctbal)   AS avg_balance        -- NUMBER with a long scale
FROM snowflake_sample_data.tpch_sf1.customer AS c
JOIN snowflake_sample_data.tpch_sf1.nation   AS n ON n.n_nationkey = c.c_nationkey
GROUP BY 1, 2
ORDER BY 1, 2
