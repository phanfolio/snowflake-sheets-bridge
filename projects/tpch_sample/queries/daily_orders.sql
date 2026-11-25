-- Orders per day and priority: 1.5M TPC-H orders aggregated to roughly 12k rows.
SELECT
    o_orderdate                    AS order_date,        -- DATE
    o_orderpriority                AS order_priority,    -- VARCHAR
    o_orderpriority = '1-URGENT'   AS is_urgent,         -- BOOLEAN
    COUNT(*)                       AS orders,            -- integer NUMBER
    SUM(o_totalprice)              AS revenue,           -- NUMBER(p,2)
    AVG(o_totalprice)              AS avg_order_value    -- NUMBER with a long scale
FROM snowflake_sample_data.tpch_sf1.orders
GROUP BY 1, 2, 3
ORDER BY 1, 2
