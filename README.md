---

# 价格监控系统产品需求文档

## 1. 文档概览

本系统旨在建立一个高频（秒级）、跨链、跨平台的行情监控中心。通过统一的配置和数据标准，监控 CEX（中心化交易所）现货与合约、以及 DEX（去中心化交易所，以 Astar 生态为核心）的价格与衍生品指标。

## 2. 系统架构

系统由 **采集层 (Collector)**、**数据存储层 (Database)** 和 **任务管理层 (Configuration)** 组成。

---

## 3. 数据库设计 (Database Schema)

### 3.1 交易所表 (`exchanges`)

统一存储 CEX 和 DEX 平台信息。

| **字段名** | **类型** | **说明** |
| --- | --- | --- |
| **id** | SMALLINT | 交易所/DEX ID (主键) |
| **name** | VARCHAR(32) | 平台名称 (唯一) |

#### 交易所 ID 映射

| **ID** | **名称** | **类型** |
| --- | --- | --- |
| 0 | binance | CEX |
| 2 | bybit | CEX |
| 3 | okx | CEX |
| 4 | gate | CEX |
| 5 | kraken | CEX |
| 6 | aster | CEX |
| 7 | alpha | CEX |
| 8 | pancake_v3 | DEX |
| 9 | pancake_v4 | DEX |
| 10 | uniswap_v4 | DEX |
| 11 | aero_v3 | DEX |
| 12 | uniswap_v3 | DEX |

### 3.2 Token 表 (`tokens`)

| **字段名** | **类型** | **说明** |
| --- | --- | --- |
| **id** | SMALLINT | Token ID (主键) |
| **name** | VARCHAR(32) | Token 名称 (唯一) |

#### Token ID 映射

| **ID** | **名称** |
| --- | --- |
| 0 | usd1 |
| 1 | usdt |
| 2 | space |
| 3 | rave |

### 3.3 任务配置表 (`config_monitoring_tasks`)

| **字段名** | **类型** | **说明** | **示例** |
| --- | --- | --- | --- |
| **id** | SERIAL | 自增主键 | `1` |
| **exchange_id** | SMALLINT | 交易所 ID (外键 → exchanges) | `6` (aster) |
| **base_token_id** | SMALLINT | 基础 Token ID (外键 → tokens) | `3` (rave) |
| **quote_token_id** | SMALLINT | 报价 Token ID (外键 → tokens) | `0` (usd1) |
| **platform_type** | VARCHAR(8) | 类型 | `CEX` 或 `DEX` |
| **remote_id** | VARCHAR(128) | 物理标识 | CEX 填交易对, DEX 填池地址 |
| **extra_params** | JSONB | 扩展参数 | `{"include_spot": true}` |
| **update_interval** | INT | 采样频率(秒) | `5` |
| **price_precision** | SMALLINT | 价格小数位数 | `2` |
| **is_active** | BOOLEAN | 是否启用 | `true` |
| **created_at** | TIMESTAMPTZ | 创建时间 | |
| **updated_at** | TIMESTAMPTZ | 更新时间 | |

**唯一约束：** `(exchange_id, remote_id)`  
**索引：** `is_active`, `platform_type`, `exchange_id`

### 3.4 CEX 实时行情表 (`mm_cex_latest`)

存储 CEX 的全量指标，支持现货与合约。

| **字段名** | **类型** | **说明** | **适用范围** |
| --- | --- | --- | --- |
| **exchange_id** | SMALLINT | 交易所 ID (外键 → exchanges) | 共有 |
| **symbol** | VARCHAR(32) | 统一币对标识 (例如 rave_usd1) | 共有 |
| **spot_price** | NUMERIC(36, 18) | 现货最新成交价 | 现货 |
| **best_bid** | NUMERIC(36, 18) | 现货买一价 | 现货 |
| **best_ask** | NUMERIC(36, 18) | 现货卖一价 | 现货 |
| **fut_price** | NUMERIC(36, 18) | 合约最新成交价 | 合约 |
| **fut_index** | NUMERIC(36, 18) | 合约指数价格 | 合约 |
| **fut_mark** | NUMERIC(36, 18) | 合约标记价格 | 合约 |
| **funding_rate** | NUMERIC(16, 8) | 资金费率 | 合约 |
| **funding_interval** | VARCHAR(16) | 资金费结算周期 | 合约 |
| **timestamp** | TIMESTAMPTZ | 数据采集/产生时间 | 共有 |

**主键：** `(exchange_id, symbol)`  
**外键：** `exchange_id → exchanges(id)`

### 3.5 CEX 历史行情表 (`mm_cex_historical`)

与 `mm_cex_latest` 结构相同，按时间范围分区存储历史数据。

**主键：** `(exchange_id, symbol, timestamp)`  
**分区方式：** `PARTITION BY RANGE (timestamp)`  
**索引：** `exchange_id`, `symbol`, `timestamp`

### 3.6 DEX 实时行情表 (`mm_dex_latest`)

存储链上池子价格。

| **字段名** | **类型** | **说明** |
| --- | --- | --- |
| **exchange_id** | SMALLINT | DEX ID (外键 → exchanges) |
| **symbol** | VARCHAR(32) | 统一币对标识 (例如 rave_usdt) |
| **pool_address** | VARCHAR(42) | 流动性池合约地址 |
| **spot_price** | NUMERIC(36, 18) | 链上即时兑换价格 |
| **timestamp** | TIMESTAMPTZ | 数据采集时间 |

**主键：** `(exchange_id, symbol, pool_address)`  
**外键：** `exchange_id → exchanges(id)`

### 3.7 DEX 历史行情表 (`mm_dex_historical`)

与 `mm_dex_latest` 结构相同，按时间范围分区存储历史数据。

**主键：** `(exchange_id, symbol, pool_address, timestamp)`  
**分区方式：** `PARTITION BY RANGE (timestamp)`  
**索引：** `exchange_id`, `symbol`, `timestamp`

---

## 4. 数据采集

- **CEX 模块：**
    - 使用 CCXT 库统一获取各交易所数据
    - 对于现货（Spot），合约相关字段置为 `NULL`
    - 启动时自动获取 `price_precision` 并存入配置表
    - 价格按 `price_precision` 格式化后存储

- **DEX 模块：**
    - 根据 `remote_id` (池地址) 通过 RPC 调用
    - 需支持价格反转逻辑（如果池子是 USDT/ASTR，则价格需取倒数）

---

## 5. 性能与非功能需求

- **高频写入：** `latest` 表使用 `UPSERT` 逻辑（主键冲突则更新），减少索引压力。
- **异常处理：** 当连续 3 个采集周期获取不到数据时，触发"数据源离线"告警。
- **历史存证：** 所有的 `mm_cex_latest` / `mm_dex_latest` 写入操作必须同步一份副本到对应的 `mm_cex_historical` / `mm_dex_historical` 表。

---

## 6. 运维配置流程

### 6.1 使用 manage_tasks.py 管理任务

```bash
# 查看所有交易所和 Token
python manage_tasks.py show-platforms

# 添加新交易所
python manage_tasks.py add-exchange 13 hyperliquid

# 添加新 Token
python manage_tasks.py add-token 4 btc

# 添加 CEX 监控任务
python manage_tasks.py add-cex aster rave usd1 --interval 5

# 添加 DEX 监控任务
python manage_tasks.py add-dex pancake_v3 rave usdt 0x1234... --interval 5

# 查看所有任务
python manage_tasks.py list

# 启用/禁用任务
python manage_tasks.py enable 1
python manage_tasks.py disable 1

# 删除任务
python manage_tasks.py delete 1
```

### 6.2 启动采集器

```bash
python collector.py
```

采集引擎从 `config_monitoring_tasks` 表读取配置，自动开启轮询任务。

---
