# Bra monitoring query rules

- Prefer `product_daily_latest` for current product metrics. Do not aggregate `product_daily_history` by default.
- Prefer `keyword_period_latest` for current keyword metrics.
- History models are append-only and may contain multiple versions for one business date. Never sum versions unless explicitly studying revisions.
- `metric_date` and `period_start` are business dates. `observed_at` is collection time.
- Amazon is primarily analyzed by brand and parent-ASIN family. TikTok Shop is primarily analyzed by shop and product_id.
- Count products with `COUNT(DISTINCT family_id)` to avoid version and offer duplication.
- GMV and units follow provider definitions. Current FastMoss monetary data is USD.
- Current rows are a small seed sample and must not be described as the entire bra market.
