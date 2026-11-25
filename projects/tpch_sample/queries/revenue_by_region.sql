-- Revenue by region, nation and market segment: 25 nations x 5 segments = 125 rows.
WITH by_segment AS (
    SELECT
        r.r_name                       AS region,             -- VARCHAR
        n.n_name                       AS nation,
        c.c_mktsegment                 AS market_segment,
        COUNT(DISTINCT o.o_custkey)    AS customers,          -- integer NUMBER
        SUM(o.o_totalprice)            AS revenue,            -- NUMBER(p,2)
        MIN(o.o_orderdate)             AS first_order_date,   -- DATE
        MAX(o.o_orderdate)             AS last_order_date
    FROM snowflake_sample_data.tpch_sf1.orders   AS o
    JOIN snowflake_sample_data.tpch_sf1.customer AS c ON c.c_custkey   = o.o_custkey
    JOIN snowflake_sample_data.tpch_sf1.nation   AS n ON n.n_nationkey = c.c_nationkey
    JOIN snowflake_sample_data.tpch_sf1.region   AS r ON r.r_regionkey = n.n_regionkey
    GROUP BY 1, 2, 3
)
SELECT
    *,
    CURRENT_TIMESTAMP()                AS computed_at          -- TIMESTAMP_LTZ: should land as UTC
FROM by_segment
ORDER BY region, nation, market_segment
