-- 25 rows. Primary key: NATIONKEY. Foreign key: REGIONKEY -> region.
SELECT n_nationkey AS nationkey, n_name AS nation_name, n_regionkey AS regionkey
FROM snowflake_sample_data.tpch_sf1.nation
ORDER BY 1
