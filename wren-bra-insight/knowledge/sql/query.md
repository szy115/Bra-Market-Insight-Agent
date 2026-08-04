---
nl: 比较不同文胸属性的销量和价格
sql: "WITH base AS (\n  SELECT p.id AS family_id, p.wire_structure, p.strap_presence,\
  \ p.closure_type, p.cup_construction, p.cup_coverage, p.back_style, p.band_length,\
  \ d.units_daily, d.gmv_daily, d.price\n  FROM product_daily_latest d JOIN products\
  \ p ON d.family_id = p.id\n), attrs AS (\n  SELECT family_id, 'wire_structure' AS\
  \ attribute_axis, wire_structure AS attribute_value, units_daily, gmv_daily, price\
  \ FROM base\n  UNION ALL SELECT family_id, 'strap_presence', strap_presence, units_daily,\
  \ gmv_daily, price FROM base\n  UNION ALL SELECT family_id, 'closure_type', closure_type,\
  \ units_daily, gmv_daily, price FROM base\n  UNION ALL SELECT family_id, 'cup_construction',\
  \ cup_construction, units_daily, gmv_daily, price FROM base\n  UNION ALL SELECT\
  \ family_id, 'cup_coverage', cup_coverage, units_daily, gmv_daily, price FROM base\n\
  \  UNION ALL SELECT family_id, 'back_style', back_style, units_daily, gmv_daily,\
  \ price FROM base\n  UNION ALL SELECT family_id, 'band_length', band_length, units_daily,\
  \ gmv_daily, price FROM base\n)\nSELECT attribute_axis, attribute_value, COUNT(DISTINCT\
  \ family_id) AS product_count, SUM(units_daily) AS units_daily, ROUND(AVG(price),\
  \ 2) AS avg_list_price, ROUND(SUM(gmv_daily) / NULLIF(SUM(units_daily), 0), 2) AS\
  \ weighted_gmv_per_unit\nFROM attrs GROUP BY attribute_axis, attribute_value ORDER\
  \ BY attribute_axis, units_daily DESC"
source: user
---
