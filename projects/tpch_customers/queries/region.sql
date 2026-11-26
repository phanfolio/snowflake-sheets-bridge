-- 5 rows. Primary key: REGIONKEY.
SELECT r_regionkey AS regionkey, r_name AS region_name
FROM snowflake_sample_data.tpch_sf1.region
ORDER BY 1
