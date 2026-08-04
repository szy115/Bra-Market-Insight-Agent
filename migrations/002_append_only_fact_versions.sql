SET NAMES utf8mb4;
SET time_zone = '+00:00';

ALTER TABLE bra_product_daily
    DROP PRIMARY KEY,
    ADD COLUMN id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT FIRST,
    ADD COLUMN observed_at DATETIME(3) NULL AFTER source_call_id,
    ADD COLUMN version INT UNSIGNED NOT NULL DEFAULT 1 AFTER observed_at,
    ADD PRIMARY KEY (id);

UPDATE bra_product_daily f
LEFT JOIN source_call c ON c.id = f.source_call_id
SET f.observed_at = COALESCE(c.completed_at, TIMESTAMP(f.metric_date, '23:59:59'))
WHERE f.observed_at IS NULL;

ALTER TABLE bra_product_daily
    MODIFY observed_at DATETIME(3) NOT NULL,
    ADD UNIQUE KEY uk_product_daily_version
        (metric_date, provider, family_id, period_days, version),
    ADD KEY idx_product_daily_latest
        (provider, family_id, period_days, metric_date, observed_at, version);

ALTER TABLE bra_keyword_period
    DROP PRIMARY KEY,
    ADD COLUMN id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT FIRST,
    ADD COLUMN observed_at DATETIME(3) NULL AFTER source_call_id,
    ADD COLUMN version INT UNSIGNED NOT NULL DEFAULT 1 AFTER observed_at,
    ADD PRIMARY KEY (id);

UPDATE bra_keyword_period f
LEFT JOIN source_call c ON c.id = f.source_call_id
SET f.observed_at = COALESCE(c.completed_at, TIMESTAMP(f.period_start, '23:59:59'))
WHERE f.observed_at IS NULL;

ALTER TABLE bra_keyword_period
    MODIFY observed_at DATETIME(3) NOT NULL,
    ADD UNIQUE KEY uk_keyword_period_version
        (provider, market, keyword_id, period_type, period_start, version),
    ADD KEY idx_keyword_period_latest
        (provider, market, keyword_id, period_type, period_start, observed_at, version);

ALTER TABLE bra_product_keyword_period
    DROP PRIMARY KEY,
    ADD COLUMN id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT FIRST,
    ADD COLUMN observed_at DATETIME(3) NULL AFTER source_call_id,
    ADD COLUMN version INT UNSIGNED NOT NULL DEFAULT 1 AFTER observed_at,
    ADD PRIMARY KEY (id);

UPDATE bra_product_keyword_period f
LEFT JOIN source_call c ON c.id = f.source_call_id
SET f.observed_at = COALESCE(c.completed_at, TIMESTAMP(f.period_start, '23:59:59'))
WHERE f.observed_at IS NULL;

ALTER TABLE bra_product_keyword_period
    MODIFY observed_at DATETIME(3) NOT NULL,
    ADD UNIQUE KEY uk_product_keyword_version
        (provider, family_id, keyword_id, period_start, traffic_type, version),
    ADD KEY idx_product_keyword_latest
        (provider, family_id, keyword_id, period_start, traffic_type, observed_at, version);

ALTER TABLE bra_content_product_daily
    DROP PRIMARY KEY,
    ADD COLUMN id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT FIRST,
    ADD COLUMN observed_at DATETIME(3) NULL AFTER source_call_id,
    ADD COLUMN version INT UNSIGNED NOT NULL DEFAULT 1 AFTER observed_at,
    ADD PRIMARY KEY (id);

UPDATE bra_content_product_daily f
LEFT JOIN source_call c ON c.id = f.source_call_id
SET f.observed_at = COALESCE(c.completed_at, TIMESTAMP(f.metric_date, '23:59:59'))
WHERE f.observed_at IS NULL;

ALTER TABLE bra_content_product_daily
    MODIFY observed_at DATETIME(3) NOT NULL,
    ADD UNIQUE KEY uk_content_product_daily_version
        (metric_date, provider, content_id, family_id, version),
    ADD KEY idx_content_product_daily_latest
        (provider, content_id, family_id, metric_date, observed_at, version);

CREATE OR REPLACE VIEW bra_product_daily_latest AS
SELECT ranked.*
FROM (
    SELECT f.*,
           ROW_NUMBER() OVER (
               PARTITION BY metric_date, provider, family_id, period_days
               ORDER BY observed_at DESC, version DESC, id DESC
           ) AS version_rank
    FROM bra_product_daily f
) ranked
WHERE ranked.version_rank = 1;

CREATE OR REPLACE VIEW bra_keyword_period_latest AS
SELECT ranked.*
FROM (
    SELECT f.*,
           ROW_NUMBER() OVER (
               PARTITION BY provider, market, keyword_id, period_type, period_start
               ORDER BY observed_at DESC, version DESC, id DESC
           ) AS version_rank
    FROM bra_keyword_period f
) ranked
WHERE ranked.version_rank = 1;

CREATE OR REPLACE VIEW bra_product_keyword_period_latest AS
SELECT ranked.*
FROM (
    SELECT f.*,
           ROW_NUMBER() OVER (
               PARTITION BY provider, family_id, keyword_id, period_start, traffic_type
               ORDER BY observed_at DESC, version DESC, id DESC
           ) AS version_rank
    FROM bra_product_keyword_period f
) ranked
WHERE ranked.version_rank = 1;

CREATE OR REPLACE VIEW bra_content_product_daily_latest AS
SELECT ranked.*
FROM (
    SELECT f.*,
           ROW_NUMBER() OVER (
               PARTITION BY metric_date, provider, content_id, family_id
               ORDER BY observed_at DESC, version DESC, id DESC
           ) AS version_rank
    FROM bra_content_product_daily f
) ranked
WHERE ranked.version_rank = 1;

