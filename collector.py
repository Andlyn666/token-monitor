"""
Main price collector orchestrator
Runs CEX and DEX collectors concurrently
Loads task configuration dynamically from database
"""
import asyncio
import json
import logging
import os
import signal
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional, Set
from cex.cex_base import format_price, SpotData, FuturesData, CexPriceData

# CEX_MAP and DEX_MAP are now stored in database (exchanges table)
from db.database import Database
from cex.ccxt_collector import create_cex_collector, CcxtCollector

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Configure logging (WARNING level by default, DEBUG if DEBUG env var is set)
log_level = logging.DEBUG if os.getenv('DEBUG') else logging.WARNING
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('collector.log'),
    ]
)
logger = logging.getLogger(__name__)


def get_proxy_config() -> Optional[Dict]:
    """Get proxy configuration from environment variables"""
    proxy = os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY')
    if proxy:
        logger.info(f"Using proxy: {proxy}")
        return {
            'proxies': {
                'http': proxy,
                'https': proxy,
            },
            'aiohttp_proxy': proxy,
        }
    return None


class PriceCollector:
    """
    Main price collector that orchestrates CEX and DEX data collection
    Tasks are loaded dynamically from database on each collection cycle
    """
    
    def __init__(self):
        self.db = Database()
        self.cex_collectors: Dict[str, CcxtCollector] = {}
        self.dex_collectors: Dict[str, object] = {}  # Cache DEX collectors
        self.running = False
        self.proxy_config = get_proxy_config()  # Load proxy config once
        
        # Track failure counts for alerting
        self.failure_counts: Dict[str, int] = {}
        self.max_failure_count = 3
        
        # Track active task IDs for change detection
        self.active_cex_tasks: Set[int] = set()
        self.active_dex_tasks: Set[int] = set()

    async def start(self):
        """Start the collector"""
        logger.info("Starting price collector...")
        
        # Connect to database
        await self.db.connect()
        
        # Initialize tables if not exists
        await self.db.init_tables()
        
        self.running = True
        
        # Start main collection loops
        cex_task = asyncio.create_task(self._cex_collection_loop())
        dex_task = asyncio.create_task(self._dex_collection_loop())
        
        logger.info("Price collector started, loading tasks from database...")
        
        # Wait for both loops
        await asyncio.gather(cex_task, dex_task, return_exceptions=True)

    async def stop(self):
        """Stop the collector gracefully"""
        logger.info("Stopping price collector...")
        self.running = False
        
        # Close CEX collectors
        for collector in self.cex_collectors.values():
            try:
                await collector.close()
            except Exception as e:
                logger.error(f"Error closing collector: {e}")
        
        # Close database
        await self.db.close()
        
        logger.info("Price collector stopped")

    async def _ensure_cex_collector(self, exchange_name: str, exchange_id: int) -> Optional[CcxtCollector]:
        """Get or create CEX collector for the exchange"""
        exchange_lower = exchange_name.lower()
        
        if exchange_lower in self.cex_collectors:
            return self.cex_collectors[exchange_lower]
        
        try:
            collector = create_cex_collector(exchange_lower, exchange_id, self.proxy_config)
            self.cex_collectors[exchange_lower] = collector
            logger.info(f"Initialized CEX collector for {exchange_name}")
            return collector
        except Exception as e:
            logger.error(f"Failed to create CEX collector for {exchange_name}: {e}")
            return None

    async def _ensure_precision_loaded(self, task: dict, collector: CcxtCollector) -> Optional[int]:
        """
        Ensure price_precision is loaded for a task
        If not present in task, fetch from exchange and save to database
        Returns the precision value
        """
        precision = task.get('price_precision')
        
        if precision is not None:
            return precision
        
        # Parse extra params
        extra_params = task.get('extra_params', {})
        if isinstance(extra_params, str):
            extra_params = json.loads(extra_params) if extra_params else {}
        
        # For Binance Alpha, use stored alpha_decimals from extra_params
        if task['exchange_name'].lower() == 'alpha' and extra_params.get('alpha_decimals'):
            precision = int(extra_params['alpha_decimals'])
            await self.db.update_task_precision(task['id'], precision)
            task['price_precision'] = precision
            logger.info(f"[{task['exchange_name']}] Using stored precision for {task['base_token']}: {precision}")
            return precision
        
        # Fetch precision from exchange (use futures symbol)
        symbol = task.get('fut_symbol') or task.get('spot_symbol')
        if not symbol:
            return None
        try:
            precision = await collector.get_price_precision(symbol)
            if precision is not None:
                # Save to database
                await self.db.update_task_precision(task['id'], precision)
                task['price_precision'] = precision
                logger.info(f"[{task['exchange_name']}] Loaded price precision for {symbol}: {precision}")
            return precision
        except Exception as e:
            logger.error(f"[{task['exchange_name']}] Failed to get precision for {symbol}: {e}")
            return None

    def _format_cex_prices(self, data, precision: int):
        """
        Format CEX price data with the specified precision
        Args:
            data: CexPriceData object
            precision: Number of decimal places
        Returns:
            CexPriceData with formatted prices
        """
        
        
        formatted_spot = None
        formatted_futures = None
        
        if data.spot:
            formatted_spot = SpotData(
                price=format_price(data.spot.price, precision),
                best_bid=format_price(data.spot.best_bid, precision),
                best_ask=format_price(data.spot.best_ask, precision),
            )
        
        if data.futures:
            formatted_futures = FuturesData(
                price=format_price(data.futures.price, precision),
                index_price=format_price(data.futures.index_price, precision),
                mark_price=format_price(data.futures.mark_price, precision),
                funding_rate=data.futures.funding_rate,  # Don't format funding rate
                funding_interval=data.futures.funding_interval,
            )
        
        return CexPriceData(
            cex=data.cex,
            base_token=data.base_token,
            spot_symbol=data.spot_symbol,
            fut_symbol=data.fut_symbol,
            spot=formatted_spot,
            futures=formatted_futures,
            timestamp=data.timestamp,
        )

    async def _get_dex_collector(self, exchange_name: str, pool_address: str, extra_params: dict):
        """Get or create DEX collector"""
        cache_key = f"{exchange_name}:{pool_address}"
        
        if cache_key in self.dex_collectors:
            return self.dex_collectors[cache_key]
        
        dex_name = exchange_name.lower()
        # Get quote token address from extra_params
        quote_token_address = extra_params.get('quote_token_address')
        chain = extra_params.get('chain', '').lower()
        
        # Get appropriate RPC based on chain
        rpc_map = {
            'bsc': os.getenv('BSC_RPC'),
            'ethereum': os.getenv('ETH_RPC'),
            'eth': os.getenv('ETH_RPC'),
            'base': os.getenv('BASE_RPC'),
            'arbitrum': os.getenv('ARB_RPC'),
            'arb': os.getenv('ARB_RPC'),
        }
        rpc_url = rpc_map.get(chain) or os.getenv('ETH_RPC')
        
        try:
            from web3 import Web3
            web3 = Web3(Web3.HTTPProvider(rpc_url)) if rpc_url else None
            
            # Get additional params from extra_params
            base_token_address = extra_params.get('base_token_address')
            
            collector = None
            if dex_name == 'pancake_v3':
                from dex.pancake_v3 import PancakeV3Dex
                collector = PancakeV3Dex(pool_address, quote_token_address, web3)
            elif dex_name == 'pancake_v4':
                from dex.pancake_v4 import PancakeV4Dex
                # V4: pool_address is the pair_id, manager address is hardcoded in class
                collector = PancakeV4Dex(pool_address, quote_token_address, web3, base_token_address=base_token_address)
            elif dex_name == 'uniswap_v3':
                from dex.uniswap_v3 import UniswapV3Dex
                collector = UniswapV3Dex(pool_address, quote_token_address, web3)
            elif dex_name == 'uniswap_v4':
                from dex.uniswap_v4 import UniswapV4Dex
                # V4: pool_address is the pair_id, state view address is hardcoded in class
                collector = UniswapV4Dex(pool_address, quote_token_address, web3, base_token_address=base_token_address)
            elif dex_name == 'aero_v3':
                from dex.aerodrome_v3 import AerodromeV3Dex
                collector = AerodromeV3Dex(pool_address, quote_token_address, web3)
            
            if collector:
                self.dex_collectors[cache_key] = collector
                logger.info(f"Initialized DEX collector for {exchange_name}:{pool_address} on {chain or 'default'}")
            return collector
        except Exception as e:
            logger.error(f"Failed to create DEX collector for {exchange_name}: {e}")
            import traceback
            logger.debug(f"DEX collector error traceback:\n{traceback.format_exc()}")
            return None

    async def _cex_collection_loop(self):
        """Main CEX collection loop - reads tasks from DB each cycle"""
        while self.running:
            try:
                # Load active CEX tasks from database
                tasks = await self.db.get_active_cex_tasks()
                
                if not tasks:
                    logger.debug("No active CEX tasks found")
                    await asyncio.sleep(5)
                    continue
                
                # Group tasks by interval for efficient collection
                min_interval = min(t['update_interval'] for t in tasks)
                
                # Collect data for each task concurrently
                collect_tasks = []
                for task in tasks:
                    collect_tasks.append(self._collect_cex_data(task))
                
                if collect_tasks:
                    await asyncio.gather(*collect_tasks, return_exceptions=True)
                
                # Sleep for minimum interval
                await asyncio.sleep(min_interval)
                
            except Exception as e:
                logger.error(f"CEX collection loop error: {e}")
                await asyncio.sleep(5)

    async def _dex_collection_loop(self):
        """Main DEX collection loop - reads tasks from DB each cycle"""
        while self.running:
            try:
                # Load active DEX tasks from database
                tasks = await self.db.get_active_dex_tasks()
                
                if not tasks:
                    logger.debug("No active DEX tasks found")
                    await asyncio.sleep(5)
                    continue
                
                # Group tasks by interval for efficient collection
                min_interval = min(t['update_interval'] for t in tasks)
                
                # Collect data for each task concurrently
                collect_tasks = []
                for task in tasks:
                    collect_tasks.append(self._collect_dex_data(task))
                
                if collect_tasks:
                    await asyncio.gather(*collect_tasks, return_exceptions=True)
                
                # Sleep for minimum interval
                await asyncio.sleep(min_interval)
                
            except Exception as e:
                logger.error(f"DEX collection loop error: {e}")
                await asyncio.sleep(5)

    async def _collect_cex_data(self, task: dict):
        """Collect data for a single CEX task"""
        task_id = task['id']
        exchange_name = task['exchange_name']
        base_token = task['base_token']
        
        # 现货和合约可能使用不同的交易对
        spot_symbol = task.get('spot_symbol')  # e.g., rave_usd1
        fut_symbol = task.get('fut_symbol')    # e.g., rave_usdt
        
        task_key = f"cex:{exchange_name}:{base_token}"
        
        # Parse extra params
        extra_params = task.get('extra_params', {})
        if isinstance(extra_params, str):
            extra_params = json.loads(extra_params) if extra_params else {}
        
        # 根据配置决定是否采集现货/合约
        include_spot = spot_symbol and task.get('spot_quote_token_id') is not None
        include_futures = fut_symbol and task.get('fut_quote_token_id') is not None
        
        collector = await self._ensure_cex_collector(exchange_name, task['exchange_id'])
        if not collector:
            return
        
        # Ensure price precision is loaded (use futures symbol for precision)
        precision = await self._ensure_precision_loaded(task, collector)
        
        try:
            spot_data = None
            futures_data = None
            
            # 并行获取现货和合约数据
            async def fetch_spot():
                if include_spot and spot_symbol:
                    try:
                        alpha_id = task.get('spot_remote_id') if exchange_name.lower() == 'alpha' else None
                        return await collector.get_spot_price(spot_symbol, alpha_id=alpha_id)
                    except Exception as e:
                        import traceback
                        logger.warning(f"[{exchange_name}] Failed to get spot for {spot_symbol}: {type(e).__name__}: {e}")
                        logger.debug(f"[{exchange_name}] Spot error traceback:\n{traceback.format_exc()}")
                return None
            
            async def fetch_futures():
                if include_futures and fut_symbol:
                    try:
                        return await collector.get_futures_price(fut_symbol)
                    except Exception as e:
                        import traceback
                        logger.warning(f"[{exchange_name}] Failed to get futures for {fut_symbol}: {type(e).__name__}: {e}")
                        logger.debug(f"[{exchange_name}] Futures error traceback:\n{traceback.format_exc()}")
                return None
            
            # 并行执行
            spot_data, futures_data = await asyncio.gather(fetch_spot(), fetch_futures())
            
            # 构建价格数据
            data = CexPriceData(
                cex=task['exchange_id'],
                base_token=base_token,
                spot_symbol=spot_symbol if include_spot else None,
                fut_symbol=fut_symbol if include_futures else None,
                spot=spot_data,
                futures=futures_data,
                timestamp=datetime.utcnow(),
            )
            
            # Format prices with precision if available
            if precision is not None:
                data = self._format_cex_prices(data, precision)
            
            # Save to database
            await self.db.upsert_cex_latest_from_data(data)
            
            # Reset failure count on success
            self.failure_counts[task_key] = 0
            
            logger.debug(f"[{exchange_name}] Collected {base_token}: "
                        f"spot({spot_symbol})={data.spot.price if data.spot else None}, "
                        f"fut({fut_symbol})={data.futures.price if data.futures else None}")
            
        except Exception as e:
            self.failure_counts[task_key] = self.failure_counts.get(task_key, 0) + 1
            logger.error(f"[{exchange_name}] Error collecting {base_token}: {e}")
            
            # Check for alert threshold
            if self.failure_counts[task_key] >= self.max_failure_count:
                logger.warning(f"ALERT: {task_key} has failed {self.failure_counts[task_key]} times consecutively!")

    async def _collect_dex_data(self, task: dict):
        """Collect data for a single DEX task"""
        task_id = task['id']
        exchange_name = task['exchange_name']
        symbol = task['unified_symbol']
        pool_address = task['remote_id']  # For DEX, remote_id is pool address
        task_key = f"dex:{exchange_name}:{pool_address}"
        
        # Parse extra params
        extra_params = task.get('extra_params', {})
        if isinstance(extra_params, str):
            extra_params = json.loads(extra_params) if extra_params else {}
        
        # Get exchange ID from task (already fetched from database)
        exchange_id = task['exchange_id']
        
        collector = await self._get_dex_collector(exchange_name, pool_address, extra_params)
        if not collector:
            return
        
        try:
            # Get price from DEX
            price = collector.get_price()
            
            # Save to database
            await self.db.upsert_dex_latest(
                exchange_id=exchange_id,
                symbol=symbol,
                pool_address=pool_address,
                spot_price=Decimal(str(price)) if price else None,
                timestamp=datetime.utcnow(),
            )
            
            # Reset failure count on success
            self.failure_counts[task_key] = 0
            
            logger.debug(f"[{exchange_name}] Collected {symbol}: price={price}")
            
        except Exception as e:
            self.failure_counts[task_key] = self.failure_counts.get(task_key, 0) + 1
            logger.error(f"[{exchange_name}] Error collecting {symbol}: {e}")
            
            # Check for alert threshold
            if self.failure_counts[task_key] >= self.max_failure_count:
                logger.warning(f"ALERT: {task_key} has failed {self.failure_counts[task_key]} times consecutively!")


async def main():
    """Main entry point"""
    collector = PriceCollector()
    
    # Handle graceful shutdown
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        logger.info("Received shutdown signal")
        collector.running = False
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)
    
    try:
        await collector.start()
    except KeyboardInterrupt:
        pass
    finally:
        await collector.stop()


if __name__ == "__main__":
    asyncio.run(main())
