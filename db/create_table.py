# 交易所表
CREATE_EXCHANGES = """
CREATE TABLE IF NOT EXISTS exchanges (
    id SMALLINT PRIMARY KEY,                  -- 交易所 ID
    name VARCHAR(32) NOT NULL UNIQUE          -- 交易所名称
);

-- 初始化交易所数据 (CEX: 0-7, DEX: 8+)
INSERT INTO exchanges (id, name) VALUES
    -- CEX
    (0, 'binance'),
    (1, 'bitget'),
    (2, 'bybit'),
    (3, 'okx'),
    (4, 'gate'),
    (5, 'kraken'),
    (6, 'aster'),
    (7, 'alpha'),
    -- DEX
    (8, 'pancake_v3'),
    (9, 'pancake_v4'),
    (10, 'uniswap_v4'),
    (11, 'aero_v3'),
    (12, 'uniswap_v3')
ON CONFLICT (id) DO NOTHING;
"""

# Token 表
CREATE_TOKENS = """
CREATE TABLE IF NOT EXISTS tokens (
    id SMALLINT PRIMARY KEY,                  -- Token ID
    name VARCHAR(32) NOT NULL UNIQUE          -- Token 名称
);

-- 初始化 Token 数据
INSERT INTO tokens (id, name) VALUES
    (0, 'usd1'),
    (1, 'usdt'),
    (2, 'space'),
    (3, 'rave')
ON CONFLICT (id) DO NOTHING;
"""

# 任务配置表
CREATE_CONFIG_MONITORING_TASKS = """
CREATE TABLE IF NOT EXISTS config_monitoring_tasks (
    id SERIAL PRIMARY KEY,                    -- 自增主键
    exchange_id SMALLINT NOT NULL,            -- 交易所 ID (引用 exchanges 表)
    base_token_id SMALLINT NOT NULL,          -- 基础 Token ID (引用 tokens 表)
    -- 现货配置
    spot_quote_token_id SMALLINT,             -- 现货报价 Token ID (引用 tokens 表)
    spot_remote_id VARCHAR(128),              -- 现货交易对标识 (例如 RAVEUSD1)
    -- 合约配置  
    fut_quote_token_id SMALLINT,              -- 合约报价 Token ID (引用 tokens 表)
    fut_remote_id VARCHAR(128),               -- 合约交易对标识 (例如 RAVEUSDT)
    -- 通用配置
    platform_type VARCHAR(8) NOT NULL,        -- 类型: CEX 或 DEX
    extra_params JSONB DEFAULT '{}',          -- 扩展参数
    update_interval INT DEFAULT 5,            -- 采样频率(秒)
    price_precision SMALLINT DEFAULT NULL,    -- 价格小数位数 (从 exchangeInfo 获取)
    is_active BOOLEAN DEFAULT true,           -- 是否启用
    created_at TIMESTAMPTZ DEFAULT NOW(),     -- 创建时间
    updated_at TIMESTAMPTZ DEFAULT NOW(),     -- 更新时间
    -- 外键约束
    FOREIGN KEY (exchange_id) REFERENCES exchanges(id),
    FOREIGN KEY (base_token_id) REFERENCES tokens(id),
    FOREIGN KEY (spot_quote_token_id) REFERENCES tokens(id),
    FOREIGN KEY (fut_quote_token_id) REFERENCES tokens(id)
);

-- 唯一约束：同一交易所+基础币+报价币组合只能有一条记录
-- 使用 COALESCE 处理 NULL 值 (NULL 变为 -1)
CREATE UNIQUE INDEX IF NOT EXISTS idx_config_tasks_unique_pair 
ON config_monitoring_tasks (
    exchange_id, 
    base_token_id, 
    COALESCE(spot_quote_token_id, -1), 
    COALESCE(fut_quote_token_id, -1)
);

-- 为配置表创建索引
CREATE INDEX IF NOT EXISTS idx_config_tasks_active ON config_monitoring_tasks (is_active);
CREATE INDEX IF NOT EXISTS idx_config_tasks_platform_type ON config_monitoring_tasks (platform_type);
CREATE INDEX IF NOT EXISTS idx_config_tasks_exchange ON config_monitoring_tasks (exchange_id);
"""

# 创建最新数据表
CREATE_MM_CEX_LATEST = """
CREATE TABLE mm_cex_latest (
    exchange_id SMALLINT NOT NULL,         -- 交易所 ID (引用 exchanges 表)
    base_token VARCHAR(32) NOT NULL,       -- 基础币标识 (e.g., rave)
    -- 现货数据
    spot_symbol VARCHAR(32) NOT NULL DEFAULT '',  -- 现货交易对 (e.g., rave_usd1)
    spot_price NUMERIC,                    -- 现货最新成交价
    best_bid NUMERIC,                      -- 现货买一价
    best_ask NUMERIC,                      -- 现货卖一价
    -- 合约数据
    fut_symbol VARCHAR(32) NOT NULL DEFAULT '',   -- 合约交易对 (e.g., rave_usdt)
    fut_price NUMERIC,                     -- 合约最新成交价
    fut_index NUMERIC,                     -- 合约指数价格
    fut_mark NUMERIC,                      -- 合约标记价格
    funding_rate NUMERIC,                  -- 资金费率
    funding_interval VARCHAR(16),          -- 资金费结算周期
    timestamp TIMESTAMPTZ NOT NULL,        -- 数据采集/产生时间
    -- 外键约束
    FOREIGN KEY (exchange_id) REFERENCES exchanges(id),
    -- 复合主键：支持同一交易所的多个币对
    PRIMARY KEY (exchange_id, base_token, spot_symbol, fut_symbol)
);
"""

# 创建历史表主表（按时间范围分区）
CREATE_MM_CEX_HISTORICAL = """
CREATE TABLE mm_cex_historical (
    exchange_id SMALLINT NOT NULL,         -- 交易所 ID (引用 exchanges 表)
    base_token VARCHAR(32) NOT NULL,       -- 基础币标识 (e.g., rave)
    -- 现货数据
    spot_symbol VARCHAR(32) NOT NULL DEFAULT '',  -- 现货交易对 (e.g., rave_usd1)
    spot_price NUMERIC,                    -- 现货最新成交价
    best_bid NUMERIC,                      -- 现货买一价
    best_ask NUMERIC,                      -- 现货卖一价
    -- 合约数据
    fut_symbol VARCHAR(32) NOT NULL DEFAULT '',   -- 合约交易对 (e.g., rave_usdt)
    fut_price NUMERIC,                     -- 合约最新成交价
    fut_index NUMERIC,                     -- 合约指数价格
    fut_mark NUMERIC,                      -- 合约标记价格
    funding_rate NUMERIC,                  -- 资金费率
    funding_interval VARCHAR(16),          -- 资金费结算周期
    timestamp TIMESTAMPTZ NOT NULL,        -- 数据产生时间
    -- 在分区表中，主键必须包含分区键 (timestamp)
    PRIMARY KEY (exchange_id, base_token, spot_symbol, fut_symbol, timestamp)
) PARTITION BY RANGE (timestamp);
"""

# 为历史表创建索引
CREATE_MM_CEX_HISTORICAL_INDEXES = """
-- 按交易所查询的索引
CREATE INDEX IF NOT EXISTS idx_mm_cex_historical_exchange ON mm_cex_historical (exchange_id);

-- 按基础币查询的索引
CREATE INDEX IF NOT EXISTS idx_mm_cex_historical_base_token ON mm_cex_historical (base_token);

-- 按时间查询的索引
CREATE INDEX IF NOT EXISTS idx_mm_cex_historical_timestamp ON mm_cex_historical (timestamp);
"""

# 创建 DEX 最新数据表
CREATE_MM_DEX_LATEST = """
CREATE TABLE mm_dex_latest (
    exchange_id SMALLINT NOT NULL,         -- DEX ID (引用 exchanges 表)
    symbol VARCHAR(32) NOT NULL,           -- 统一币对标识 (例如 astr_usdt)
    pool_address VARCHAR(66) NOT NULL,     -- 流动性池地址或V4 pair_id (bytes32=66字符)
    spot_price NUMERIC,                    -- 链上即时兑换价格
    timestamp TIMESTAMPTZ NOT NULL,        -- 数据采集时间
    -- 外键约束
    FOREIGN KEY (exchange_id) REFERENCES exchanges(id),
    -- 复合主键：区分同一交易所内不同池子的同名币对
    PRIMARY KEY (exchange_id, symbol, pool_address)
);
"""

# 创建 DEX 历史表主表（按时间范围分区）
CREATE_MM_DEX_HISTORICAL = """
CREATE TABLE mm_dex_historical (
    exchange_id SMALLINT NOT NULL,         -- DEX ID (引用 exchanges 表)
    symbol VARCHAR(32) NOT NULL,
    pool_address VARCHAR(66) NOT NULL,     -- 流动性池地址或V4 pair_id (bytes32=66字符)
    spot_price NUMERIC,                    -- 链上即时兑换价格
    timestamp TIMESTAMPTZ NOT NULL,
    -- 分区表主键必须包含分区键 (timestamp)
    PRIMARY KEY (exchange_id, symbol, pool_address, timestamp)
) PARTITION BY RANGE (timestamp);
"""

# 为 DEX 历史表创建索引
CREATE_MM_DEX_HISTORICAL_INDEXES = """
-- 按 DEX 查询的索引
CREATE INDEX IF NOT EXISTS idx_mm_dex_historical_exchange ON mm_dex_historical (exchange_id);

-- 按币对查询的索引
CREATE INDEX IF NOT EXISTS idx_mm_dex_historical_symbol ON mm_dex_historical (symbol);

-- 按时间查询的索引
CREATE INDEX IF NOT EXISTS idx_mm_dex_historical_timestamp ON mm_dex_historical (timestamp);
"""

# 创建历史表分区 (按月分区)
CREATE_CEX_HISTORICAL_PARTITIONS = """
-- 2026 年分区
CREATE TABLE IF NOT EXISTS mm_cex_historical_2026_01 PARTITION OF mm_cex_historical
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE IF NOT EXISTS mm_cex_historical_2026_02 PARTITION OF mm_cex_historical
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
CREATE TABLE IF NOT EXISTS mm_cex_historical_2026_03 PARTITION OF mm_cex_historical
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
CREATE TABLE IF NOT EXISTS mm_cex_historical_2026_04 PARTITION OF mm_cex_historical
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE IF NOT EXISTS mm_cex_historical_2026_05 PARTITION OF mm_cex_historical
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE IF NOT EXISTS mm_cex_historical_2026_06 PARTITION OF mm_cex_historical
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
CREATE TABLE IF NOT EXISTS mm_cex_historical_2026_07 PARTITION OF mm_cex_historical
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
CREATE TABLE IF NOT EXISTS mm_cex_historical_2026_08 PARTITION OF mm_cex_historical
    FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE IF NOT EXISTS mm_cex_historical_2026_09 PARTITION OF mm_cex_historical
    FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE IF NOT EXISTS mm_cex_historical_2026_10 PARTITION OF mm_cex_historical
    FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
CREATE TABLE IF NOT EXISTS mm_cex_historical_2026_11 PARTITION OF mm_cex_historical
    FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
CREATE TABLE IF NOT EXISTS mm_cex_historical_2026_12 PARTITION OF mm_cex_historical
    FOR VALUES FROM ('2026-12-01') TO ('2027-01-01');
"""

CREATE_DEX_HISTORICAL_PARTITIONS = """
-- 2026 年分区
CREATE TABLE IF NOT EXISTS mm_dex_historical_2026_01 PARTITION OF mm_dex_historical
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE IF NOT EXISTS mm_dex_historical_2026_02 PARTITION OF mm_dex_historical
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
CREATE TABLE IF NOT EXISTS mm_dex_historical_2026_03 PARTITION OF mm_dex_historical
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
CREATE TABLE IF NOT EXISTS mm_dex_historical_2026_04 PARTITION OF mm_dex_historical
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE IF NOT EXISTS mm_dex_historical_2026_05 PARTITION OF mm_dex_historical
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE IF NOT EXISTS mm_dex_historical_2026_06 PARTITION OF mm_dex_historical
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
CREATE TABLE IF NOT EXISTS mm_dex_historical_2026_07 PARTITION OF mm_dex_historical
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
CREATE TABLE IF NOT EXISTS mm_dex_historical_2026_08 PARTITION OF mm_dex_historical
    FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE IF NOT EXISTS mm_dex_historical_2026_09 PARTITION OF mm_dex_historical
    FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE IF NOT EXISTS mm_dex_historical_2026_10 PARTITION OF mm_dex_historical
    FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
CREATE TABLE IF NOT EXISTS mm_dex_historical_2026_11 PARTITION OF mm_dex_historical
    FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
CREATE TABLE IF NOT EXISTS mm_dex_historical_2026_12 PARTITION OF mm_dex_historical
    FOR VALUES FROM ('2026-12-01') TO ('2027-01-01');
"""

# 汇率最新表
CREATE_EXCHANGE_RATES_LATEST = """
CREATE TABLE IF NOT EXISTS exchange_rates_latest (
    currency VARCHAR(16) PRIMARY KEY,      -- 货币代码 (e.g., 'eur', 'btc')
    rate_to_usdt NUMERIC NOT NULL,         -- 对 USDT 的汇率
    updated_at TIMESTAMPTZ NOT NULL        -- 更新时间
);

-- 初始化 EUR
INSERT INTO exchange_rates_latest (currency, rate_to_usdt, updated_at) VALUES
    ('eur', 1.0, NOW())
ON CONFLICT (currency) DO NOTHING;
"""

# 汇率历史表 (按月分区)
CREATE_EXCHANGE_RATES_HISTORICAL = """
CREATE TABLE IF NOT EXISTS exchange_rates_historical (
    currency VARCHAR(16) NOT NULL,         -- 货币代码
    rate_to_usdt NUMERIC NOT NULL,         -- 对 USDT 的汇率
    recorded_at TIMESTAMPTZ NOT NULL,      -- 记录时间
    PRIMARY KEY (currency, recorded_at)
) PARTITION BY RANGE (recorded_at);
"""

# 汇率历史表分区
CREATE_EXCHANGE_RATES_PARTITIONS = """
-- 2026 年分区
CREATE TABLE IF NOT EXISTS exchange_rates_historical_2026_01 PARTITION OF exchange_rates_historical
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE IF NOT EXISTS exchange_rates_historical_2026_02 PARTITION OF exchange_rates_historical
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
CREATE TABLE IF NOT EXISTS exchange_rates_historical_2026_03 PARTITION OF exchange_rates_historical
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
CREATE TABLE IF NOT EXISTS exchange_rates_historical_2026_04 PARTITION OF exchange_rates_historical
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE IF NOT EXISTS exchange_rates_historical_2026_05 PARTITION OF exchange_rates_historical
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE IF NOT EXISTS exchange_rates_historical_2026_06 PARTITION OF exchange_rates_historical
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
CREATE TABLE IF NOT EXISTS exchange_rates_historical_2026_07 PARTITION OF exchange_rates_historical
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
CREATE TABLE IF NOT EXISTS exchange_rates_historical_2026_08 PARTITION OF exchange_rates_historical
    FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
CREATE TABLE IF NOT EXISTS exchange_rates_historical_2026_09 PARTITION OF exchange_rates_historical
    FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE IF NOT EXISTS exchange_rates_historical_2026_10 PARTITION OF exchange_rates_historical
    FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
CREATE TABLE IF NOT EXISTS exchange_rates_historical_2026_11 PARTITION OF exchange_rates_historical
    FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
CREATE TABLE IF NOT EXISTS exchange_rates_historical_2026_12 PARTITION OF exchange_rates_historical
    FOR VALUES FROM ('2026-12-01') TO ('2027-01-01');
"""

# 迁移语句：为现有表添加字段
ALTER_ADD_PRICE_PRECISION = """
ALTER TABLE config_monitoring_tasks 
ADD COLUMN IF NOT EXISTS price_precision SMALLINT DEFAULT NULL;
"""

# 迁移语句：添加新字段到现有 config_monitoring_tasks 表
ALTER_ADD_TOKEN_FIELDS = """
-- 添加 exchange_id 字段
ALTER TABLE config_monitoring_tasks 
ADD COLUMN IF NOT EXISTS exchange_id SMALLINT;

-- 添加 base_token_id 字段
ALTER TABLE config_monitoring_tasks 
ADD COLUMN IF NOT EXISTS base_token_id SMALLINT;

-- 添加现货/合约分离字段
ALTER TABLE config_monitoring_tasks 
ADD COLUMN IF NOT EXISTS spot_quote_token_id SMALLINT;

ALTER TABLE config_monitoring_tasks 
ADD COLUMN IF NOT EXISTS spot_remote_id VARCHAR(128);

ALTER TABLE config_monitoring_tasks 
ADD COLUMN IF NOT EXISTS fut_quote_token_id SMALLINT;

ALTER TABLE config_monitoring_tasks 
ADD COLUMN IF NOT EXISTS fut_remote_id VARCHAR(128);
"""

# 迁移语句：扩展 pool_address 字段长度以支持 V4 pair_id (bytes32)
ALTER_POOL_ADDRESS_LENGTH = """
-- 修改 mm_dex_latest 表的 pool_address 字段
ALTER TABLE mm_dex_latest 
ALTER COLUMN pool_address TYPE VARCHAR(66);

-- 修改 mm_dex_historical 表的 pool_address 字段
ALTER TABLE mm_dex_historical 
ALTER COLUMN pool_address TYPE VARCHAR(66);
"""

# 迁移语句：修改唯一约束以支持同一交易所的多个币对
ALTER_UNIQUE_CONSTRAINT = """
-- 删除旧的唯一约束 (如果存在)
ALTER TABLE config_monitoring_tasks 
DROP CONSTRAINT IF EXISTS config_monitoring_tasks_exchange_id_base_token_id_key;

-- 创建新的唯一索引 (支持同一交易所的多个币对)
DROP INDEX IF EXISTS idx_config_tasks_unique_pair;
CREATE UNIQUE INDEX idx_config_tasks_unique_pair 
ON config_monitoring_tasks (
    exchange_id, 
    base_token_id, 
    COALESCE(spot_quote_token_id, -1), 
    COALESCE(fut_quote_token_id, -1)
);
"""

# 迁移语句：修改 CEX 表主键以支持同一 base_token 的多个币对
ALTER_CEX_PRIMARY_KEY = """
-- Step 1: 更新现有 NULL 值为空字符串
UPDATE mm_cex_latest SET spot_symbol = '' WHERE spot_symbol IS NULL;
UPDATE mm_cex_latest SET fut_symbol = '' WHERE fut_symbol IS NULL;
UPDATE mm_cex_historical SET spot_symbol = '' WHERE spot_symbol IS NULL;
UPDATE mm_cex_historical SET fut_symbol = '' WHERE fut_symbol IS NULL;

-- Step 2: 修改 mm_cex_latest 表
ALTER TABLE mm_cex_latest 
ALTER COLUMN spot_symbol SET NOT NULL,
ALTER COLUMN spot_symbol SET DEFAULT '',
ALTER COLUMN fut_symbol SET NOT NULL,
ALTER COLUMN fut_symbol SET DEFAULT '';

ALTER TABLE mm_cex_latest DROP CONSTRAINT mm_cex_latest_pkey;
ALTER TABLE mm_cex_latest ADD PRIMARY KEY (exchange_id, base_token, spot_symbol, fut_symbol);

-- Step 3: 修改 mm_cex_historical 表
ALTER TABLE mm_cex_historical 
ALTER COLUMN spot_symbol SET NOT NULL,
ALTER COLUMN spot_symbol SET DEFAULT '',
ALTER COLUMN fut_symbol SET NOT NULL,
ALTER COLUMN fut_symbol SET DEFAULT '';

ALTER TABLE mm_cex_historical DROP CONSTRAINT mm_cex_historical_pkey;
ALTER TABLE mm_cex_historical ADD PRIMARY KEY (exchange_id, base_token, spot_symbol, fut_symbol, timestamp);
"""

# 清理旧分区的函数 (删除超过 N 个月的历史数据)
CREATE_CLEANUP_FUNCTION = """
CREATE OR REPLACE FUNCTION cleanup_old_partitions(months_to_keep INTEGER DEFAULT 3)
RETURNS TEXT AS $$
DECLARE
    cutoff_date DATE;
    partition_name TEXT;
    dropped_count INTEGER := 0;
    result TEXT := '';
BEGIN
    cutoff_date := DATE_TRUNC('month', CURRENT_DATE - (months_to_keep || ' months')::INTERVAL);
    
    -- 清理 mm_cex_historical 分区
    FOR partition_name IN
        SELECT tablename FROM pg_tables 
        WHERE tablename LIKE 'mm_cex_historical_____\\___' 
        AND schemaname = 'public'
    LOOP
        IF TO_DATE(SUBSTRING(partition_name FROM 'mm_cex_historical_(\\d{4}_\\d{2})'), 'YYYY_MM') < cutoff_date THEN
            EXECUTE 'DROP TABLE IF EXISTS ' || partition_name;
            dropped_count := dropped_count + 1;
            result := result || 'Dropped: ' || partition_name || E'\\n';
        END IF;
    END LOOP;
    
    -- 清理 mm_dex_historical 分区
    FOR partition_name IN
        SELECT tablename FROM pg_tables 
        WHERE tablename LIKE 'mm_dex_historical_____\\___' 
        AND schemaname = 'public'
    LOOP
        IF TO_DATE(SUBSTRING(partition_name FROM 'mm_dex_historical_(\\d{4}_\\d{2})'), 'YYYY_MM') < cutoff_date THEN
            EXECUTE 'DROP TABLE IF EXISTS ' || partition_name;
            dropped_count := dropped_count + 1;
            result := result || 'Dropped: ' || partition_name || E'\\n';
        END IF;
    END LOOP;
    
    -- 清理 exchange_rates_historical 分区
    FOR partition_name IN
        SELECT tablename FROM pg_tables 
        WHERE tablename LIKE 'exchange_rates_historical_____\\___' 
        AND schemaname = 'public'
    LOOP
        IF TO_DATE(SUBSTRING(partition_name FROM 'exchange_rates_historical_(\\d{4}_\\d{2})'), 'YYYY_MM') < cutoff_date THEN
            EXECUTE 'DROP TABLE IF EXISTS ' || partition_name;
            dropped_count := dropped_count + 1;
            result := result || 'Dropped: ' || partition_name || E'\\n';
        END IF;
    END LOOP;
    
    IF dropped_count = 0 THEN
        RETURN 'No partitions older than ' || cutoff_date || ' found.';
    END IF;
    
    RETURN result || 'Total dropped: ' || dropped_count || ' partitions.';
END;
$$ LANGUAGE plpgsql;
"""