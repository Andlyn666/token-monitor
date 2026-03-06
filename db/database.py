"""
Async database operations using asyncpg
"""
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional, List
import asyncpg

from config import DatabaseConfig

logger = logging.getLogger(__name__)


class Database:
    """
    Async database manager for price monitoring data
    """
    
    def __init__(self, config: Optional[DatabaseConfig] = None):
        self.config = config or DatabaseConfig()
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Create connection pool"""
        self.pool = await asyncpg.create_pool(
            dsn=self.config.dsn,
            min_size=self.config.min_connections,
            max_size=self.config.max_connections,
        )
        logger.info("Database connection pool created")

    async def close(self):
        """Close connection pool"""
        if self.pool:
            await self.pool.close()
            logger.info("Database connection pool closed")

    async def init_tables(self):
        """Initialize database tables"""
        from db.create_table import (
            CREATE_EXCHANGES,
            CREATE_TOKENS,
            CREATE_CONFIG_MONITORING_TASKS,
            CREATE_MM_CEX_LATEST,
            CREATE_MM_CEX_HISTORICAL,
            CREATE_MM_CEX_HISTORICAL_INDEXES,
            CREATE_CEX_HISTORICAL_PARTITIONS,
            CREATE_MM_DEX_LATEST,
            CREATE_MM_DEX_HISTORICAL,
            CREATE_MM_DEX_HISTORICAL_INDEXES,
            CREATE_DEX_HISTORICAL_PARTITIONS,
            CREATE_EXCHANGE_RATES_LATEST,
            CREATE_EXCHANGE_RATES_HISTORICAL,
            CREATE_EXCHANGE_RATES_PARTITIONS,
            CREATE_CLEANUP_FUNCTION,
            ALTER_ADD_PRICE_PRECISION,
            ALTER_ADD_TOKEN_FIELDS,
        )
        
        async with self.pool.acquire() as conn:
            # Create tables in order (exchanges/tokens must be created before config_monitoring_tasks)
            for sql in [
                CREATE_EXCHANGES,
                CREATE_TOKENS,
                CREATE_CONFIG_MONITORING_TASKS,
                CREATE_MM_CEX_LATEST,
                CREATE_MM_CEX_HISTORICAL,
                CREATE_MM_CEX_HISTORICAL_INDEXES,
                CREATE_CEX_HISTORICAL_PARTITIONS,
                CREATE_MM_DEX_LATEST,
                CREATE_MM_DEX_HISTORICAL,
                CREATE_MM_DEX_HISTORICAL_INDEXES,
                CREATE_DEX_HISTORICAL_PARTITIONS,
                CREATE_EXCHANGE_RATES_LATEST,
                CREATE_EXCHANGE_RATES_HISTORICAL,
                CREATE_EXCHANGE_RATES_PARTITIONS,
                CREATE_CLEANUP_FUNCTION,
            ]:
                try:
                    await conn.execute(sql)
                except asyncpg.exceptions.DuplicateTableError:
                    pass
                except asyncpg.exceptions.DuplicateObjectError:
                    pass
            
            # Run migrations for existing tables
            for migration in [ALTER_ADD_PRICE_PRECISION, ALTER_ADD_TOKEN_FIELDS]:
                try:
                    await conn.execute(migration)
                except Exception:
                    pass  # Column may already exist
        
        logger.info("Database tables initialized")

    # =========================================================================
    # Task Configuration Operations
    # =========================================================================

    async def get_active_cex_tasks(self) -> List[dict]:
        """
        Get all active CEX monitoring tasks from config table
        Returns list of task configurations with exchange and token names
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT 
                    t.id, 
                    t.exchange_id,
                    e.name as exchange_name,
                    t.base_token_id,
                    bt.name as base_token,
                    -- 现货配置
                    t.spot_quote_token_id,
                    sqt.name as spot_quote_token,
                    t.spot_remote_id,
                    CASE WHEN sqt.name IS NOT NULL THEN bt.name || '_' || sqt.name ELSE NULL END as spot_symbol,
                    -- 合约配置
                    t.fut_quote_token_id,
                    fqt.name as fut_quote_token,
                    t.fut_remote_id,
                    CASE WHEN fqt.name IS NOT NULL THEN bt.name || '_' || fqt.name ELSE NULL END as fut_symbol,
                    -- 通用配置
                    t.extra_params, 
                    t.update_interval, 
                    t.price_precision
                FROM config_monitoring_tasks t
                JOIN exchanges e ON t.exchange_id = e.id
                JOIN tokens bt ON t.base_token_id = bt.id
                LEFT JOIN tokens sqt ON t.spot_quote_token_id = sqt.id
                LEFT JOIN tokens fqt ON t.fut_quote_token_id = fqt.id
                WHERE t.platform_type = 'CEX' AND t.is_active = true
                ORDER BY e.name, bt.name
                """
            )
            return [dict(row) for row in rows]

    async def get_active_dex_tasks(self) -> List[dict]:
        """
        Get all active DEX monitoring tasks from config table
        Returns list of task configurations with exchange and token names
        DEX uses spot_quote_token_id and spot_remote_id (pool address)
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT 
                    t.id, 
                    t.exchange_id,
                    e.name as exchange_name,
                    t.base_token_id,
                    bt.name as base_token,
                    t.spot_quote_token_id as quote_token_id,
                    sqt.name as quote_token,
                    CASE WHEN sqt.name IS NOT NULL THEN bt.name || '_' || sqt.name ELSE NULL END as unified_symbol,
                    t.spot_remote_id as remote_id,
                    t.extra_params, 
                    t.update_interval
                FROM config_monitoring_tasks t
                JOIN exchanges e ON t.exchange_id = e.id
                JOIN tokens bt ON t.base_token_id = bt.id
                LEFT JOIN tokens sqt ON t.spot_quote_token_id = sqt.id
                WHERE t.platform_type = 'DEX' AND t.is_active = true
                ORDER BY e.name, bt.name
                """
            )
            return [dict(row) for row in rows]

    async def get_all_active_tasks(self) -> dict:
        """
        Get all active monitoring tasks grouped by type
        Returns: {'cex': [...], 'dex': [...]}
        """
        cex_tasks = await self.get_active_cex_tasks()
        dex_tasks = await self.get_active_dex_tasks()
        return {
            'cex': cex_tasks,
            'dex': dex_tasks
        }

    async def add_task(
        self,
        exchange_id: int,
        base_token_id: int,
        platform_type: str,
        # 现货配置 (可选)
        spot_quote_token_id: Optional[int] = None,
        spot_remote_id: Optional[str] = None,
        # 合约配置 (可选)
        fut_quote_token_id: Optional[int] = None,
        fut_remote_id: Optional[str] = None,
        # 通用配置
        extra_params: Optional[dict] = None,
        update_interval: int = 5,
        is_active: bool = True,
    ) -> int:
        """
        Add a new monitoring task or update existing one
        Unique key: (exchange_id, base_token_id, spot_quote_token_id, fut_quote_token_id)
        Returns: task id
        """
        import json
        async with self.pool.acquire() as conn:
            # Check if task with same unique key exists
            existing = await conn.fetchrow(
                """
                SELECT id FROM config_monitoring_tasks 
                WHERE exchange_id = $1 
                  AND base_token_id = $2 
                  AND COALESCE(spot_quote_token_id, -1) = COALESCE($3, -1)
                  AND COALESCE(fut_quote_token_id, -1) = COALESCE($4, -1)
                """,
                exchange_id, base_token_id, spot_quote_token_id, fut_quote_token_id
            )
            
            if existing:
                # Update existing task
                await conn.execute(
                    """
                    UPDATE config_monitoring_tasks SET
                        spot_remote_id = $1,
                        fut_remote_id = $2,
                        extra_params = $3,
                        update_interval = $4,
                        is_active = $5,
                        updated_at = NOW()
                    WHERE id = $6
                    """,
                    spot_remote_id, fut_remote_id,
                    json.dumps(extra_params or {}), update_interval, is_active,
                    existing['id']
                )
                return existing['id']
            else:
                # Insert new task
                row = await conn.fetchrow(
                    """
                    INSERT INTO config_monitoring_tasks 
                        (exchange_id, base_token_id, spot_quote_token_id, spot_remote_id,
                         fut_quote_token_id, fut_remote_id, platform_type,
                         extra_params, update_interval, is_active)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    RETURNING id
                    """,
                    exchange_id, base_token_id, spot_quote_token_id, spot_remote_id,
                    fut_quote_token_id, fut_remote_id, platform_type,
                    json.dumps(extra_params or {}), update_interval, is_active
                )
                return row['id']

    async def update_task_status(self, task_id: int, is_active: bool):
        """Enable or disable a task"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE config_monitoring_tasks 
                SET is_active = $2, updated_at = NOW()
                WHERE id = $1
                """,
                task_id, is_active
            )

    async def delete_task(self, task_id: int):
        """Delete a task by id"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM config_monitoring_tasks WHERE id = $1",
                task_id
            )

    async def get_task_precision(self, task_id: int) -> Optional[int]:
        """Get price_precision for a task"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT price_precision FROM config_monitoring_tasks WHERE id = $1",
                task_id
            )
            return row['price_precision'] if row else None

    async def update_task_precision(self, task_id: int, precision: int):
        """Update price_precision for a task"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE config_monitoring_tasks 
                SET price_precision = $2, updated_at = NOW()
                WHERE id = $1
                """,
                task_id, precision
            )

    async def get_cex_tasks_without_precision(self) -> List[dict]:
        """
        Get all active CEX tasks that don't have price_precision set
        Returns list of task configurations
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT 
                    t.id, 
                    t.exchange_id,
                    e.name as exchange_name,
                    t.base_token_id,
                    bt.name as base_token,
                    t.fut_quote_token_id,
                    fqt.name as fut_quote_token,
                    t.fut_remote_id,
                    CASE WHEN fqt.name IS NOT NULL THEN bt.name || '_' || fqt.name ELSE NULL END as fut_symbol,
                    t.extra_params, 
                    t.update_interval
                FROM config_monitoring_tasks t
                JOIN exchanges e ON t.exchange_id = e.id
                JOIN tokens bt ON t.base_token_id = bt.id
                LEFT JOIN tokens fqt ON t.fut_quote_token_id = fqt.id
                WHERE t.platform_type = 'CEX' 
                  AND t.is_active = true 
                  AND t.price_precision IS NULL
                ORDER BY e.name, bt.name
                """
            )
            return [dict(row) for row in rows]

    async def get_exchange_by_name(self, name: str) -> Optional[dict]:
        """Get exchange by name"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, name FROM exchanges WHERE name = $1",
                name.lower()
            )
            return dict(row) if row else None

    async def get_token_by_name(self, name: str) -> Optional[dict]:
        """Get token by name"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, name FROM tokens WHERE name = $1",
                name.lower()
            )
            return dict(row) if row else None

    async def get_all_exchanges(self) -> List[dict]:
        """Get all exchanges"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, name FROM exchanges ORDER BY id")
            return [dict(row) for row in rows]

    async def get_all_tokens(self) -> List[dict]:
        """Get all tokens"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, name FROM tokens ORDER BY id")
            return [dict(row) for row in rows]

    async def add_exchange(self, id: int, name: str):
        """Add a new exchange"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO exchanges (id, name) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
                id, name.lower()
            )

    async def add_token(self, id: int, name: str):
        """Add a new token"""
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO tokens (id, name) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
                id, name.lower()
            )

    # =========================================================================
    # CEX Operations
    # =========================================================================

    async def upsert_cex_latest(
        self,
        exchange_id: int,
        base_token: str,
        spot_symbol: Optional[str] = None,
        spot_price: Optional[Decimal] = None,
        best_bid: Optional[Decimal] = None,
        best_ask: Optional[Decimal] = None,
        fut_symbol: Optional[str] = None,
        fut_price: Optional[Decimal] = None,
        fut_index: Optional[Decimal] = None,
        fut_mark: Optional[Decimal] = None,
        funding_rate: Optional[Decimal] = None,
        funding_interval: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ):
        """
        Upsert CEX latest price data
        Also inserts into historical table
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        # Convert None to empty string for primary key columns
        spot_symbol = spot_symbol or ''
        fut_symbol = fut_symbol or ''
        
        async with self.pool.acquire() as conn:
            # Upsert to latest table
            await conn.execute(
                """
                INSERT INTO mm_cex_latest (
                    exchange_id, base_token, spot_symbol, spot_price, best_bid, best_ask,
                    fut_symbol, fut_price, fut_index, fut_mark, funding_rate, funding_interval, timestamp
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                ON CONFLICT (exchange_id, base_token, spot_symbol, fut_symbol) DO UPDATE SET
                    spot_price = EXCLUDED.spot_price,
                    best_bid = EXCLUDED.best_bid,
                    best_ask = EXCLUDED.best_ask,
                    fut_price = EXCLUDED.fut_price,
                    fut_index = EXCLUDED.fut_index,
                    fut_mark = EXCLUDED.fut_mark,
                    funding_rate = EXCLUDED.funding_rate,
                    funding_interval = EXCLUDED.funding_interval,
                    timestamp = EXCLUDED.timestamp
                """,
                exchange_id, base_token, spot_symbol, spot_price, best_bid, best_ask,
                fut_symbol, fut_price, fut_index, fut_mark, funding_rate, funding_interval, timestamp
            )
            
            # Insert to historical table
            await conn.execute(
                """
                INSERT INTO mm_cex_historical (
                    exchange_id, base_token, spot_symbol, spot_price, best_bid, best_ask,
                    fut_symbol, fut_price, fut_index, fut_mark, funding_rate, funding_interval, timestamp
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """,
                exchange_id, base_token, spot_symbol, spot_price, best_bid, best_ask,
                fut_symbol, fut_price, fut_index, fut_mark, funding_rate, funding_interval, timestamp
            )
        
        logger.debug(f"Upserted CEX data: exchange_id={exchange_id}, base_token={base_token}")

    async def upsert_cex_latest_from_data(self, data):
        """
        Upsert CEX data from CexPriceData object
        """
        from cex.cex_base import CexPriceData
        
        if not isinstance(data, CexPriceData):
            raise ValueError("Expected CexPriceData object")
        
        spot_price = data.spot.price if data.spot else None
        best_bid = data.spot.best_bid if data.spot else None
        best_ask = data.spot.best_ask if data.spot else None
        fut_price = data.futures.price if data.futures else None
        fut_index = data.futures.index_price if data.futures else None
        fut_mark = data.futures.mark_price if data.futures else None
        funding_rate = data.futures.funding_rate if data.futures else None
        funding_interval = data.futures.funding_interval if data.futures else None
        
        await self.upsert_cex_latest(
            exchange_id=data.cex,  # CexPriceData uses 'cex' field
            base_token=data.base_token,
            spot_symbol=data.spot_symbol,
            spot_price=spot_price,
            best_bid=best_bid,
            best_ask=best_ask,
            fut_symbol=data.fut_symbol,
            fut_price=fut_price,
            fut_index=fut_index,
            fut_mark=fut_mark,
            funding_rate=funding_rate,
            funding_interval=funding_interval,
            timestamp=data.timestamp,
        )

    async def get_cex_latest(self, exchange_id: int, base_token: str) -> Optional[dict]:
        """Get latest CEX price data"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM mm_cex_latest
                WHERE exchange_id = $1 AND base_token = $2
                """,
                exchange_id, base_token
            )
            return dict(row) if row else None
    
    async def get_all_cex_latest(self) -> List[dict]:
        """Get all latest CEX price data"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT l.*, e.name as exchange_name
                FROM mm_cex_latest l
                JOIN exchanges e ON l.exchange_id = e.id
                ORDER BY e.name, l.base_token
                """
            )
            return [dict(row) for row in rows]

    # =========================================================================
    # DEX Operations
    # =========================================================================

    async def upsert_dex_latest(
        self,
        exchange_id: int,
        symbol: str,
        pool_address: str,
        spot_price: Optional[Decimal] = None,
        timestamp: Optional[datetime] = None,
    ):
        """
        Upsert DEX latest price data
        Also inserts into historical table
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        async with self.pool.acquire() as conn:
            # Upsert to latest table
            await conn.execute(
                """
                INSERT INTO mm_dex_latest (exchange_id, symbol, pool_address, spot_price, timestamp)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (exchange_id, symbol, pool_address) DO UPDATE SET
                    spot_price = EXCLUDED.spot_price,
                    timestamp = EXCLUDED.timestamp
                """,
                exchange_id, symbol, pool_address, spot_price, timestamp
            )
            
            # Insert to historical table
            await conn.execute(
                """
                INSERT INTO mm_dex_historical (exchange_id, symbol, pool_address, spot_price, timestamp)
                VALUES ($1, $2, $3, $4, $5)
                """,
                exchange_id, symbol, pool_address, spot_price, timestamp
            )
        
        logger.debug(f"Upserted DEX data: exchange_id={exchange_id}, symbol={symbol}, pool={pool_address}")

    async def get_dex_latest(self, exchange_id: int, symbol: str, pool_address: str) -> Optional[dict]:
        """Get latest DEX price data"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM mm_dex_latest
                WHERE exchange_id = $1 AND symbol = $2 AND pool_address = $3
                """,
                exchange_id, symbol, pool_address
            )
            return dict(row) if row else None
    
    async def get_all_dex_latest(self) -> List[dict]:
        """Get all latest DEX price data"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT l.*, e.name as exchange_name
                FROM mm_dex_latest l
                JOIN exchanges e ON l.exchange_id = e.id
                ORDER BY e.name, l.symbol
                """
            )
            return [dict(row) for row in rows]

    # =========================================================================
    # Batch Operations
    # =========================================================================

    async def batch_upsert_cex(self, data_list: List):
        """Batch upsert multiple CEX price data"""
        for data in data_list:
            await self.upsert_cex_latest_from_data(data)

    async def batch_upsert_dex(self, data_list: List[dict]):
        """Batch upsert multiple DEX price data"""
        for data in data_list:
            await self.upsert_dex_latest(**data)

    # =========================================================================
    # Exchange Rate Operations
    # =========================================================================

    async def upsert_exchange_rate(
        self,
        currency: str,
        rate_to_usdt: Decimal,
        timestamp: Optional[datetime] = None,
    ):
        """
        Upsert exchange rate (currency to USDT)
        Also inserts into historical table
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        currency = currency.lower()
        
        async with self.pool.acquire() as conn:
            # Upsert to latest table
            await conn.execute(
                """
                INSERT INTO exchange_rates_latest (currency, rate_to_usdt, updated_at)
                VALUES ($1, $2, $3)
                ON CONFLICT (currency) DO UPDATE SET
                    rate_to_usdt = EXCLUDED.rate_to_usdt,
                    updated_at = EXCLUDED.updated_at
                """,
                currency, rate_to_usdt, timestamp
            )
            
            # Insert to historical table
            await conn.execute(
                """
                INSERT INTO exchange_rates_historical (currency, rate_to_usdt, recorded_at)
                VALUES ($1, $2, $3)
                """,
                currency, rate_to_usdt, timestamp
            )
        
        logger.debug(f"Upserted exchange rate: {currency} = {rate_to_usdt} USDT")

    async def get_exchange_rate(self, currency: str) -> Optional[Decimal]:
        """Get current exchange rate for a currency"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT rate_to_usdt FROM exchange_rates_latest
                WHERE currency = $1
                """,
                currency.lower()
            )
            return Decimal(str(row['rate_to_usdt'])) if row else None

    async def get_all_exchange_rates(self) -> List[dict]:
        """Get all current exchange rates"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT currency, rate_to_usdt, updated_at
                FROM exchange_rates_latest
                ORDER BY currency
                """
            )
            return [dict(row) for row in rows]

    async def get_currencies_to_update(self) -> List[str]:
        """Get list of currencies that need rate updates"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT currency FROM exchange_rates_latest"
            )
            return [row['currency'] for row in rows]

    async def batch_upsert_exchange_rates(self, rates: List[dict]):
        """Batch upsert multiple exchange rates"""
        for rate in rates:
            await self.upsert_exchange_rate(
                currency=rate['currency'],
                rate_to_usdt=rate['rate_to_usdt'],
                timestamp=rate.get('timestamp'),
            )

    # =========================================================================
    # Maintenance Operations
    # =========================================================================

    async def cleanup_old_partitions(self, months_to_keep: int = 3) -> str:
        """
        Delete historical partitions older than specified months
        Returns a summary of dropped partitions
        """
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT cleanup_old_partitions($1)",
                months_to_keep
            )
            return result
