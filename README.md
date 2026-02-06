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
| **base_token_id** | SMALLINT | 基础 Token ID (外键 → tokens) | `2` (space) |
| **spot_quote_token_id** | SMALLINT | 现货报价 Token ID | `0` (usd1) |
| **spot_remote_id** | VARCHAR(128) | 现货交易对/池地址 | `SPACE_USD1` 或 `0x8288...` |
| **fut_quote_token_id** | SMALLINT | 合约报价 Token ID | `1` (usdt) |
| **fut_remote_id** | VARCHAR(128) | 合约交易对标识 | `SPACE_USDT` |
| **platform_type** | VARCHAR(8) | 类型 | `CEX` 或 `DEX` |
| **extra_params** | JSONB | 扩展参数 | 见下方说明 |
| **update_interval** | INT | 采样频率(秒) | `5` |
| **price_precision** | SMALLINT | 价格小数位数 | `6` |
| **is_active** | BOOLEAN | 是否启用 | `true` |
| **created_at** | TIMESTAMPTZ | 创建时间 | |
| **updated_at** | TIMESTAMPTZ | 更新时间 | |

**唯一约束：** `(exchange_id, base_token_id)`  
**索引：** `is_active`, `platform_type`, `exchange_id`

#### extra_params 字段说明

| **参数** | **适用** | **说明** | **示例** |
| --- | --- | --- | --- |
| **chain** | DEX | 区块链名称 | `"bsc"`, `"ethereum"`, `"base"` |
| **base_token_address** | DEX | Base token 合约地址 | `"0x87acFA3fD7A6e0d48677D070644D76905C2bDC00"` |
| **quote_token_address** | DEX | Quote token 合约地址 | `"0x55d398326f99059fF775485246999027B3197955"` |
| **pair_id** | DEX V4 | V4 池子 ID | `"0x..."` |
| **alpha_id** | Alpha | Binance Alpha token ID | `"ALPHA_606"` |

示例：
```json
// DEX 任务
{
  "chain": "bsc",
  "base_token_address": "0x87acFA3fD7A6e0d48677D070644D76905C2bDC00",
  "quote_token_address": "0x55d398326f99059fF775485246999027B3197955"
}

// Alpha CEX 任务
{
  "alpha_id": "ALPHA_606"
}
```

### 3.4 CEX 实时行情表 (`mm_cex_latest`)

存储 CEX 的全量指标，支持现货与合约。

| **字段名** | **类型** | **说明** | **数据来源** |
| --- | --- | --- | --- |
| **exchange_id** | SMALLINT | 交易所 ID | 配置表 |
| **base_token** | VARCHAR(32) | 基础币标识 (例如 rave) | 配置表 |
| **spot_symbol** | VARCHAR(32) | 现货交易对 (例如 rave_usd1) | 配置表 |
| **spot_price** | NUMERIC | 现货最新成交价 | CCXT `fetch_ticker` → `last` |
| **best_bid** | NUMERIC | 现货买一价 | CCXT `fetch_ticker` → `bid` |
| **best_ask** | NUMERIC | 现货卖一价 | CCXT `fetch_ticker` → `ask` |
| **fut_symbol** | VARCHAR(32) | 合约交易对 (例如 rave_usdt) | 配置表 |
| **fut_price** | NUMERIC | 合约最新成交价 | CCXT `fetch_ticker` → `last` |
| **fut_index** | NUMERIC | 合约指数价格 | 见下方 API 说明 |
| **fut_mark** | NUMERIC | 合约标记价格 | 见下方 API 说明 |
| **funding_rate** | NUMERIC | 资金费率 | CCXT `fetch_funding_rate` → `fundingRate` |
| **funding_interval** | VARCHAR(16) | 资金费结算周期 | 交易所 `fundingInfo` API |
| **timestamp** | TIMESTAMPTZ | 数据采集时间 | 系统时间 |

**主键：** `(exchange_id, base_token)`  
**外键：** `exchange_id → exchanges(id)`

#### CEX 各交易所 API 详情

| **交易所** | **现货价格** | **合约价格** | **Index/Mark 价格** | **Funding Rate** |
| --- | --- | --- | --- | --- |
| **Binance** | CCXT ticker | CCXT ticker | `/fapi/v1/premiumIndex` → `indexPrice`, `markPrice` | CCXT |
| **OKX** | CCXT ticker | CCXT ticker | `/api/v5/public/mark-price`, `/api/v5/market/index-tickers` | CCXT |
| **Bitget** | CCXT ticker | CCXT ticker | CCXT ticker → `index`, `mark` | CCXT |
| **Gate** | CCXT ticker | CCXT ticker | CCXT ticker → `index`, `mark` | CCXT |
| **Aster** | CCXT ticker | CCXT ticker | `/fapi/v1/premiumIndex` | `/fapi/v1/fundingInfo` |
| **Alpha** | `/bapi/defi/v1/public/alpha-trade/ticker` | - | - | - |

### 3.5 CEX 历史行情表 (`mm_cex_historical`)

与 `mm_cex_latest` 结构相同，按时间范围分区存储历史数据。

**主键：** `(exchange_id, symbol, timestamp)`  
**分区方式：** `PARTITION BY RANGE (timestamp)`  
**索引：** `exchange_id`, `symbol`, `timestamp`

### 3.6 DEX 实时行情表 (`mm_dex_latest`)

存储链上池子价格。

| **字段名** | **类型** | **说明** | **数据来源** |
| --- | --- | --- | --- |
| **exchange_id** | SMALLINT | DEX ID | 配置表 |
| **symbol** | VARCHAR(32) | 统一币对标识 (例如 rave_usdt) | 配置表 |
| **pool_address** | VARCHAR(42) | 流动性池合约地址 | 配置表 `spot_remote_id` |
| **spot_price** | NUMERIC | 链上即时兑换价格 | 合约调用 (见下方说明) |
| **timestamp** | TIMESTAMPTZ | 数据采集时间 | 系统时间 |

**主键：** `(exchange_id, symbol, pool_address)`  
**外键：** `exchange_id → exchanges(id)`

#### DEX 价格获取方式

| **DEX** | **合约方法** | **价格计算** |
| --- | --- | --- |
| **Uniswap V3** | `pool.slot0()` → `sqrtPriceX96` | `(sqrtPriceX96 / 2^96)^2 * 10^(decimals0 - decimals1)` |
| **Pancake V3** | `pool.slot0()` → `sqrtPriceX96` | 同上 |
| **Aerodrome V3** | `pool.slot0()` → `sqrtPriceX96` | 同上 |
| **Uniswap V4** | `stateView.getSlot0(poolId)` → `sqrtPriceX96` | 同上 |
| **Pancake V4** | `poolManager.getSlot0(poolId)` → `sqrtPriceX96` | 同上 |

**注意：** 如果 `quote_token` 是 `token0`，则返回价格的倒数

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

### 4.1 价格精度设置

系统支持自动获取和配置价格精度（小数位数）：

| **来源** | **获取方式** | **说明** |
| --- | --- | --- |
| CEX | 从交易所 `exchangeInfo` API 获取 `tickSize` | 自动转换为小数位数（如 `0.000001` → `6`） |
| DEX | 从合约读取 token decimals | 根据 token0/token1 的 decimals 计算 |

**精度处理流程：**

1. 任务首次运行时，若 `price_precision` 为空，自动从交易所获取
2. 获取后存入 `config_monitoring_tasks.price_precision` 字段
3. 后续采集的价格按此精度格式化后存储
4. 可通过 SQL 手动重置精度，触发重新获取：
   ```sql
   UPDATE config_monitoring_tasks SET price_precision = NULL WHERE id = <task_id>;
   ```

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

# 查看所有任务
python manage_tasks.py list

# 查看最新价格
python manage_tasks.py prices          # 全部
python manage_tasks.py prices --type cex
python manage_tasks.py prices --type dex

# 启用/禁用任务
python manage_tasks.py enable <task_id>
python manage_tasks.py disable <task_id>

# 删除任务
python manage_tasks.py delete <task_id>
```

### 6.2 添加 CEX 监控任务

```bash
# 基本用法
python manage_tasks.py add-cex <exchange> <base_token> <quote_token>

# 完整参数
python manage_tasks.py add-cex <exchange> <base_token> <quote_token> \
    --spot-symbol <现货交易对>    # 可选，如 RAVE_USD1
    --fut-symbol <合约交易对>     # 可选，如 RAVE_USDT
    --spot-quote <现货报价币>     # 可选，如 usd1
    --fut-quote <合约报价币>      # 可选，如 usdt
    --interval <采集间隔秒数>     # 默认 5

# 示例：添加 Aster 的 RAVE 现货和合约
python manage_tasks.py add-cex aster rave usd1 \
    --spot-symbol RAVE_USD1 \
    --fut-symbol RAVE_USDT \
    --fut-quote usdt

# 示例：只添加合约（无现货）
python manage_tasks.py add-cex binance space usdt --fut-symbol SPACE_USDT
```

### 6.3 添加 DEX 监控任务

```bash
# 基本用法
python manage_tasks.py add-dex <dex_name> <base_token> <quote_token> <pool_address>

# 完整参数
python manage_tasks.py add-dex <dex_name> <base_token> <quote_token> <pool_address> \
    --chain <链名称>                    # 如 bsc, ethereum, base
    --base-token-address <base合约地址>  # base token 的合约地址
    --quote-token-address <quote合约地址> # quote token 的合约地址
    --interval <采集间隔秒数>            # 默认 5

# 示例：添加 BSC 上的 Uniswap V3 池
python manage_tasks.py add-dex uniswap_v3 space usdt \
    0x8288f9Bef161f16741144b65Ca0C9B78183E2f3b \
    --chain bsc \
    --base-token-address 0x87acFA3fD7A6e0d48677D070644D76905C2bDC00 \
    --quote-token-address 0x55d398326f99059fF775485246999027B3197955

# 示例：添加 Base 链上的 Aerodrome V3 池
python manage_tasks.py add-dex aero_v3 space usdc \
    0x1234567890abcdef... \
    --chain base \
    --base-token-address 0x... \
    --quote-token-address 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
```

**支持的链名称：** `bsc`, `ethereum` / `eth`, `base`, `arbitrum` / `arb`

**支持的 DEX：** `pancake_v3`, `pancake_v4`, `uniswap_v3`, `uniswap_v4`, `aero_v3`

### 6.4 启动采集器

```bash
python collector.py
```

采集引擎从 `config_monitoring_tasks` 表读取配置，自动开启轮询任务。

### 6.5 环境变量配置 (.env)

```bash
# 数据库
DB_HOST=localhost
DB_PORT=5432
DB_NAME=token_monitor
DB_USER=postgres
DB_PASSWORD=your_password

# RPC 节点（根据需要配置）
BSC_RPC=https://bsc-dataseed.binance.org/
ETH_RPC=https://eth.llamarpc.com
BASE_RPC=https://mainnet.base.org
ARB_RPC=https://arb1.arbitrum.io/rpc

# 可选：代理设置
# HTTP_PROXY=http://127.0.0.1:7890
# HTTPS_PROXY=http://127.0.0.1:7890
```

---
