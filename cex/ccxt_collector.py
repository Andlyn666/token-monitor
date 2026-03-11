"""
CCXT-based CEX data collector
Supports: Binance, Bitget, Bybit, OKX, Gate, Kraken, Aster
"""
import asyncio
import httpx
import logging
import os
from decimal import Decimal
from typing import Dict, Optional
import ccxt.async_support as ccxt

from cex.cex_base import CexBase, SpotData, FuturesData, CexPriceData

logger = logging.getLogger(__name__)


def calculate_mid_price(bid: Optional[Decimal], ask: Optional[Decimal], last: Optional[Decimal]) -> Optional[Decimal]:
    """
    Calculate price using midpoint of bid/ask, fallback to last price
    Returns: (bid + ask) / 2 if both valid, else last price
    """
    if bid and ask and bid > 0 and ask > 0:
        return (bid + ask) / 2
    return last


async def fetch_best_bid_ask(exchange, symbol: str) -> tuple:
    """
    Fetch best bid/ask from order book (limit=1 for efficiency)
    Returns: (best_bid, best_ask) as Decimal or (None, None) on error
    """
    try:
        orderbook = await exchange.fetch_order_book(symbol, limit=1)
        best_bid = Decimal(str(orderbook['bids'][0][0])) if orderbook.get('bids') and orderbook['bids'] else None
        best_ask = Decimal(str(orderbook['asks'][0][0])) if orderbook.get('asks') and orderbook['asks'] else None
        return best_bid, best_ask
    except Exception:
        return None, None


# Symbol conversion: unified format (btc_usdt) -> exchange format (BTC/USDT)
def unified_to_ccxt_symbol(symbol: str) -> str:
    """Convert unified symbol (btc_usdt) to CCXT format (BTC/USDT)"""
    parts = symbol.upper().split('_')
    if len(parts) == 2:
        return f"{parts[0]}/{parts[1]}"
    return symbol.upper()


def unified_to_ccxt_swap_symbol(symbol: str) -> str:
    """Convert unified symbol (btc_usdt) to CCXT swap format (BTC/USDT:USDT)"""
    parts = symbol.upper().split('_')
    if len(parts) == 2:
        return f"{parts[0]}/{parts[1]}:{parts[1]}"
    return symbol.upper()


class CcxtCollector(CexBase):
    """
    Generic CCXT-based collector supporting multiple exchanges
    """
    
    # Exchange class mapping
    EXCHANGE_CLASSES = {
        'binance': ccxt.binance,
        'bitget': ccxt.bitget,
        'bybit': ccxt.bybit,
        'okx': ccxt.okx,
        'gate': ccxt.gate,
        'kraken': ccxt.kraken,
        'aster': ccxt.aster,
    }

    def __init__(self, cex_id: int, cex_name: str, config: Optional[Dict] = None):
        """
        Initialize CCXT collector
        Args:
            cex_id: Exchange ID (from CEX_MAP)
            cex_name: Exchange name (lowercase, e.g., 'binance')
            config: Optional exchange config (api keys, etc.)
        """
        super().__init__(cex_id, cex_name)
        
        if cex_name.lower() not in self.EXCHANGE_CLASSES:
            raise ValueError(f"Unsupported exchange: {cex_name}")
        
        exchange_class = self.EXCHANGE_CLASSES[cex_name.lower()]
        exchange_config = config or {}
        exchange_config['enableRateLimit'] = True
        
        self.spot_exchange = exchange_class(exchange_config)
        
        # Create separate instance for futures with swap mode
        futures_config = exchange_config.copy()
        futures_config['options'] = futures_config.get('options', {})
        futures_config['options']['defaultType'] = 'swap'
        self.futures_exchange = exchange_class(futures_config)
        
        # Load markets (optional, improves performance)
        self._markets_loaded = False

    async def get_spot_price(self, symbol: str, **kwargs) -> SpotData:
        """
        Fetch spot price data using CCXT
        Price = (bid + ask) / 2 if both valid, else last price
        kwargs are ignored for CCXT-based exchanges (used by BinanceAlpha for alpha_id)
        """
        ccxt_symbol = unified_to_ccxt_symbol(symbol)
        
        # Fetch ticker data
        ticker = await self.spot_exchange.fetch_ticker(ccxt_symbol)
        
        # Debug: log raw ticker data
        if os.getenv('DEBUG_TICKER'):
            logger.warning(f"[{self.cex_name}] SPOT ticker for {symbol}: {ticker}")
        
        # Parse values
        last_price = Decimal(str(ticker['last'])) if ticker.get('last') else None
        best_bid = Decimal(str(ticker['bid'])) if ticker.get('bid') else None
        best_ask = Decimal(str(ticker['ask'])) if ticker.get('ask') else None
        
        # Calculate mid price: (bid + ask) / 2, fallback to last
        price = calculate_mid_price(best_bid, best_ask, last_price)
        
        return SpotData(
            price=price,
            best_bid=best_bid,
            best_ask=best_ask,
        )

    async def get_futures_price(self, symbol: str) -> FuturesData:
        """
        Fetch futures/perpetual price data using CCXT
        Price = (bid + ask) / 2 if both valid, else last price
        """
        ccxt_symbol = unified_to_ccxt_swap_symbol(symbol)
        
        # Fetch ticker data for futures
        ticker = await self.futures_exchange.fetch_ticker(ccxt_symbol)
        
        # Debug: log raw ticker data
        if os.getenv('DEBUG_TICKER'):
            logger.warning(f"[{self.cex_name}] FUTURES ticker for {symbol}: {ticker}")
        
        # Fetch funding rate info
        funding_rate = None
        funding_interval = None
        try:
            funding_info = await self.futures_exchange.fetch_funding_rate(ccxt_symbol)
            funding_rate = Decimal(str(funding_info['fundingRate'])) if funding_info.get('fundingRate') else None
        except Exception:
            pass

        # Try to get mark/index price
        mark_price = None
        index_price = None
        
        # Some exchanges include mark/index in ticker
        # Handle both camelCase (Bitget) and snake_case (Gate) field names
        if ticker.get('info'):
            info = ticker['info']
            # Mark price: markPrice (Bitget) or mark_price (Gate)
            mark_val = info.get('markPrice') or info.get('mark_price')
            if mark_val:
                try:
                    mark_price = Decimal(str(mark_val))
                except:
                    pass
            # Index price: indexPrice (Bitget) or index_price (Gate)
            index_val = info.get('indexPrice') or info.get('index_price')
            if index_val:
                try:
                    index_price = Decimal(str(index_val))
                except:
                    pass
        
        # Parse bid/ask/last
        last_price = Decimal(str(ticker['last'])) if ticker.get('last') else None
        best_bid = Decimal(str(ticker['bid'])) if ticker.get('bid') else None
        best_ask = Decimal(str(ticker['ask'])) if ticker.get('ask') else None
        
        # Calculate mid price: (bid + ask) / 2, fallback to last
        price = calculate_mid_price(best_bid, best_ask, last_price)
        
        return FuturesData(
            price=price,
            index_price=index_price,
            mark_price=mark_price,
            funding_rate=funding_rate,
            funding_interval=funding_interval,
        )
    
    async def get_price_precision(self, symbol: str, use_spot: bool = False) -> Optional[int]:
        """
        Get price precision (decimal places) for a symbol from exchange info
        Uses CCXT's cached markets data
        
        Args:
            symbol: Trading pair symbol (e.g., 'rave_usdt')
            use_spot: If True, use spot exchange; if False, use futures exchange
        
        Note: CCXT returns precision in different formats:
        - Some exchanges: decimal places (e.g., 6 means 6 decimal places)
        - Other exchanges: tick size (e.g., 0.000001 means 6 decimal places)
        """
        import math
        
        def tick_size_to_decimals(tick_size: float) -> int:
            """Convert tick size (e.g., 0.000001) to decimal places (e.g., 6)"""
            if tick_size <= 0:
                return 8  # Default fallback
            if tick_size >= 1:
                return 0
            # Use log10 to calculate decimal places
            return int(round(-math.log10(tick_size)))
        
        try:
            if use_spot:
                # Use spot exchange
                if not self.spot_exchange.markets:
                    await self.spot_exchange.load_markets()
                ccxt_symbol = unified_to_ccxt_symbol(symbol)
                market = self.spot_exchange.market(ccxt_symbol)
            else:
                # Use futures exchange
                if not self.futures_exchange.markets:
                    await self.futures_exchange.load_markets()
                ccxt_symbol = unified_to_ccxt_swap_symbol(symbol)
                market = self.futures_exchange.market(ccxt_symbol)
            
            if market and 'precision' in market:
                precision = market['precision']
                if isinstance(precision, dict) and 'price' in precision:
                    price_val = precision['price']
                    if isinstance(price_val, (int, float)):
                        if price_val < 1:
                            # Tick size format (e.g., 0.000001 -> 6)
                            return tick_size_to_decimals(price_val)
                        else:
                            # Already decimal places
                            return int(price_val)
                elif isinstance(precision, (int, float)):
                    if precision < 1:
                        return tick_size_to_decimals(precision)
                    return int(precision)
        except Exception as e:
            print(f"[{self.cex_name}] Failed to get price precision for {symbol}: {e}")
        
        return None

    async def close(self):
        """Close exchange connections"""
        await self.spot_exchange.close()
        await self.futures_exchange.close()


class BinanceCollector(CcxtCollector):
    def __init__(self, cex_id: int = 0, config: Optional[Dict] = None):
        super().__init__(cex_id, 'binance', config)
        self._httpx_client = None
    
    async def _get_httpx_client(self):
        """Lazy initialization of httpx client"""
        if self._httpx_client is None:
            self._httpx_client = httpx.AsyncClient(timeout=10.0)
        return self._httpx_client
    
    async def get_futures_price(self, symbol: str) -> FuturesData:
        """
        Fetch futures data for Binance with funding interval (parallel requests)
        Price = (bid + ask) / 2 if both valid, else last price
        Optimized: premiumIndex returns fundingRate, so no need for separate fetch_funding_rate
        """
        ccxt_symbol = unified_to_ccxt_swap_symbol(symbol)
        parts = symbol.upper().split('_')
        binance_symbol = f"{parts[0]}{parts[1]}" if len(parts) == 2 else symbol.replace('/', '').replace(':', '')
        
        # Define async tasks (4 requests in parallel)
        async def fetch_ticker():
            return await self.futures_exchange.fetch_ticker(ccxt_symbol)
        
        async def fetch_orderbook():
            return await fetch_best_bid_ask(self.futures_exchange, ccxt_symbol)
        
        async def fetch_premium_index():
            # Returns: markPrice, indexPrice, lastFundingRate, nextFundingTime
            try:
                client = await self._get_httpx_client()
                resp = await client.get(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={binance_symbol}")
                return resp.json() if resp.status_code == 200 else None
            except Exception:
                return None
        
        async def fetch_funding_info():
            # Returns: fundingIntervalHours
            try:
                client = await self._get_httpx_client()
                resp = await client.get(f"https://fapi.binance.com/fapi/v1/fundingInfo")
                return resp.json() if resp.status_code == 200 else None
            except Exception:
                return None
        
        # Execute all requests in parallel (4 requests)
        ticker, (ob_bid, ob_ask), premium_data, funding_info_data = await asyncio.gather(
            fetch_ticker(), fetch_orderbook(), fetch_premium_index(), fetch_funding_info()
        )
        
        # Debug: log raw ticker data
        if os.getenv('DEBUG_TICKER'):
            logger.warning(f"[binance] FUTURES ticker for {symbol}: {ticker}")
            logger.warning(f"[binance] FUTURES orderbook bid/ask: {ob_bid}/{ob_ask}")
            logger.warning(f"[binance] premiumIndex for {symbol}: {premium_data}")
        
        # Parse from premiumIndex: markPrice, indexPrice, fundingRate
        mark_price = None
        index_price = None
        funding_rate = None
        if premium_data:
            if premium_data.get('markPrice'):
                mark_price = Decimal(str(premium_data['markPrice']))
            if premium_data.get('indexPrice'):
                index_price = Decimal(str(premium_data['indexPrice']))
            if premium_data.get('lastFundingRate'):
                funding_rate = Decimal(str(premium_data['lastFundingRate']))
        
        # Parse funding interval from fundingInfo
        funding_interval = None
        if funding_info_data:
            for item in funding_info_data:
                if item.get('symbol') == binance_symbol and item.get('fundingIntervalHours'):
                    funding_interval = f"{item['fundingIntervalHours']}h"
                    break
        
        # Parse bid/ask from ticker first, fallback to order book
        last_price = Decimal(str(ticker['last'])) if ticker.get('last') else None
        best_bid = Decimal(str(ticker['bid'])) if ticker.get('bid') else ob_bid
        best_ask = Decimal(str(ticker['ask'])) if ticker.get('ask') else ob_ask
        price = calculate_mid_price(best_bid, best_ask, last_price)
        
        return FuturesData(
            price=price,
            index_price=index_price,
            mark_price=mark_price,
            funding_rate=funding_rate,
            funding_interval=funding_interval,
        )
    
    async def close(self):
        """Close exchange connections and httpx client"""
        await super().close()
        if self._httpx_client:
            await self._httpx_client.aclose()
            self._httpx_client = None


class BitgetCollector(CcxtCollector):
    def __init__(self, cex_id: int = 1, config: Optional[Dict] = None):
        super().__init__(cex_id, 'bitget', config)
        self._httpx_client = None
    
    async def _get_httpx_client(self):
        """Lazy initialization of httpx client"""
        if self._httpx_client is None:
            self._httpx_client = httpx.AsyncClient(timeout=10.0)
        return self._httpx_client
    
    async def get_futures_price(self, symbol: str) -> FuturesData:
        """
        Fetch futures data for Bitget with funding interval (parallel requests)
        Price = (bid + ask) / 2 if both valid, else last price
        """
        ccxt_symbol = unified_to_ccxt_swap_symbol(symbol)
        parts = symbol.upper().split('_')
        bitget_symbol = f"{parts[0]}{parts[1]}" if len(parts) == 2 else symbol.replace('/', '').replace(':', '')
        
        # Define async tasks
        async def fetch_ticker():
            return await self.futures_exchange.fetch_ticker(ccxt_symbol)
        
        async def fetch_funding():
            try:
                return await self.futures_exchange.fetch_funding_rate(ccxt_symbol)
            except Exception as e:
                print(f"[bitget] Failed to fetch funding info: {e}")
                return None
        
        async def fetch_contract_info():
            try:
                client = await self._get_httpx_client()
                resp = await client.get(f"https://api.bitget.com/api/v2/mix/market/contracts?productType=USDT-FUTURES&symbol={bitget_symbol}")
                if resp.status_code == 200:
                    return resp.json()
            except Exception as e:
                print(f"[bitget] Failed to fetch contract info: {e}")
            return None
        
        # Execute all requests in parallel
        ticker, funding_info, contract_data = await asyncio.gather(
            fetch_ticker(), fetch_funding(), fetch_contract_info()
        )
        
        # Debug: log raw ticker data
        if os.getenv('DEBUG_TICKER'):
            logger.warning(f"[bitget] FUTURES ticker for {symbol}: {ticker}")
        
        # Parse funding rate
        funding_rate = None
        if funding_info and funding_info.get('fundingRate'):
            funding_rate = Decimal(str(funding_info['fundingRate']))
        
        # Parse funding interval from contract info
        funding_interval = None
        if contract_data and contract_data.get('code') == '00000' and contract_data.get('data'):
            for item in contract_data['data']:
                if item.get('symbol') == bitget_symbol and item.get('fundInterval'):
                    funding_interval = f"{item['fundInterval']}h"
                    break
        
        # Get mark/index price from ticker info
        mark_price = None
        index_price = None
        if ticker.get('info'):
            info = ticker['info']
            if info.get('markPrice'):
                mark_price = Decimal(str(info['markPrice']))
            if info.get('indexPrice'):
                index_price = Decimal(str(info['indexPrice']))
        
        # Parse bid/ask/last and calculate mid price
        last_price = Decimal(str(ticker['last'])) if ticker.get('last') else None
        best_bid = Decimal(str(ticker['bid'])) if ticker.get('bid') else None
        best_ask = Decimal(str(ticker['ask'])) if ticker.get('ask') else None
        price = calculate_mid_price(best_bid, best_ask, last_price)
        
        return FuturesData(
            price=price,
            index_price=index_price,
            mark_price=mark_price,
            funding_rate=funding_rate,
            funding_interval=funding_interval,
        )
    
    async def close(self):
        """Close exchange connections and httpx client"""
        await super().close()
        if self._httpx_client:
            await self._httpx_client.aclose()
            self._httpx_client = None


class BybitCollector(CcxtCollector):
    def __init__(self, cex_id: int = 2, config: Optional[Dict] = None):
        super().__init__(cex_id, 'bybit', config)
    
    async def get_futures_price(self, symbol: str) -> FuturesData:
        """
        Fetch futures data for Bybit with funding interval
        Price = (bid + ask) / 2 if both valid, else last price
        """
        ccxt_symbol = unified_to_ccxt_swap_symbol(symbol)
        
        # Fetch ticker data
        ticker = await self.futures_exchange.fetch_ticker(ccxt_symbol)
        
        # Debug: log raw ticker data
        if os.getenv('DEBUG_TICKER'):
            logger.warning(f"[bybit] FUTURES ticker for {symbol}: {ticker}")
        
        # Fetch funding rate and interval
        funding_rate = None
        funding_interval = None
        try:
            funding_info = await self.futures_exchange.fetch_funding_rate(ccxt_symbol)
            funding_rate = Decimal(str(funding_info['fundingRate'])) if funding_info.get('fundingRate') else None
            
            # Try to get interval directly from raw info first (Bybit returns fundingInterval in minutes)
            if funding_info.get('info'):
                info = funding_info['info']
                if info.get('fundingInterval'):
                    interval_mins = int(info['fundingInterval'])
                    interval_hours = interval_mins // 60
                    funding_interval = f"{interval_hours}h"
            
            # Fallback: calculate from timestamps if no direct value
            if not funding_interval and funding_info.get('fundingTimestamp') and funding_info.get('nextFundingTimestamp'):
                interval_ms = funding_info['nextFundingTimestamp'] - funding_info['fundingTimestamp']
                interval_hours = interval_ms // (1000 * 60 * 60)
                funding_interval = f"{interval_hours}h"
        except Exception as e:
            print(f"[bybit] Failed to fetch funding info: {e}")
        
        # Get mark/index price
        mark_price = None
        index_price = None
        if ticker.get('info'):
            info = ticker['info']
            if info.get('markPrice'):
                mark_price = Decimal(str(info['markPrice']))
            if info.get('indexPrice'):
                index_price = Decimal(str(info['indexPrice']))
        
        # Parse bid/ask/last and calculate mid price
        last_price = Decimal(str(ticker['last'])) if ticker.get('last') else None
        best_bid = Decimal(str(ticker['bid'])) if ticker.get('bid') else None
        best_ask = Decimal(str(ticker['ask'])) if ticker.get('ask') else None
        price = calculate_mid_price(best_bid, best_ask, last_price)
        
        return FuturesData(
            price=price,
            index_price=index_price,
            mark_price=mark_price,
            funding_rate=funding_rate,
            funding_interval=funding_interval,
        )


class OkxCollector(CcxtCollector):
    def __init__(self, cex_id: int = 3, config: Optional[Dict] = None):
        super().__init__(cex_id, 'okx', config)
        self._httpx_client = None
    
    async def _get_httpx_client(self):
        """Lazy initialization of httpx client"""
        if self._httpx_client is None:
            self._httpx_client = httpx.AsyncClient(timeout=10.0)
        return self._httpx_client
    
    async def get_futures_price(self, symbol: str) -> FuturesData:
        """
        Fetch futures data for OKX with mark price from dedicated API (parallel requests)
        Price = (bid + ask) / 2 if both valid, else last price
        Optimized: funding-rate API returns fundingRate, so no need for separate fetch_funding_rate
        """
        ccxt_symbol = unified_to_ccxt_swap_symbol(symbol)
        parts = symbol.upper().split('_')
        base = parts[0] if len(parts) >= 1 else symbol
        quote = parts[1] if len(parts) >= 2 else 'USDT'
        okx_swap_id = f"{base}-{quote}-SWAP"
        okx_index_id = f"{base}-{quote}"
        
        # Define async tasks (4 requests in parallel)
        async def fetch_ticker():
            return await self.futures_exchange.fetch_ticker(ccxt_symbol)
        
        async def fetch_mark_price():
            try:
                client = await self._get_httpx_client()
                resp = await client.get(f"https://www.okx.com/api/v5/public/mark-price?instType=SWAP&instId={okx_swap_id}")
                return resp.json() if resp.status_code == 200 else None
            except Exception:
                return None
        
        async def fetch_index_price():
            try:
                client = await self._get_httpx_client()
                resp = await client.get(f"https://www.okx.com/api/v5/market/index-tickers?instId={okx_index_id}")
                return resp.json() if resp.status_code == 200 else None
            except Exception:
                return None
        
        async def fetch_funding_rate_api():
            # Returns: fundingRate, fundingTime, nextFundingTime
            try:
                client = await self._get_httpx_client()
                resp = await client.get(f"https://www.okx.com/api/v5/public/funding-rate?instId={okx_swap_id}")
                return resp.json() if resp.status_code == 200 else None
            except Exception:
                return None
        
        # Execute all requests in parallel (4 requests)
        ticker, mark_data, index_data, fr_data = await asyncio.gather(
            fetch_ticker(), fetch_mark_price(), fetch_index_price(), fetch_funding_rate_api()
        )
        
        # Debug: log raw ticker data
        if os.getenv('DEBUG_TICKER'):
            logger.warning(f"[okx] FUTURES ticker for {symbol}: {ticker}")
        
        # Parse mark price
        mark_price = None
        if mark_data and mark_data.get('code') == '0' and mark_data.get('data'):
            mark_price = Decimal(str(mark_data['data'][0]['markPx']))
        
        # Parse index price
        index_price = None
        if index_data and index_data.get('code') == '0' and index_data.get('data'):
            index_price = Decimal(str(index_data['data'][0]['idxPx']))
        
        # Parse funding rate and interval from funding-rate API
        funding_rate = None
        funding_interval = None
        if fr_data and fr_data.get('code') == '0' and fr_data.get('data'):
            fr_info = fr_data['data'][0]
            # Get funding rate
            if fr_info.get('fundingRate'):
                funding_rate = Decimal(str(fr_info['fundingRate']))
            # Calculate funding interval
            if fr_info.get('fundingTime') and fr_info.get('nextFundingTime'):
                current_ts = int(fr_info['fundingTime'])
                next_ts = int(fr_info['nextFundingTime'])
                interval_hours = (next_ts - current_ts) // (1000 * 60 * 60)
                funding_interval = f"{interval_hours}h"
        
        # Parse bid/ask/last and calculate mid price
        last_price = Decimal(str(ticker['last'])) if ticker.get('last') else None
        best_bid = Decimal(str(ticker['bid'])) if ticker.get('bid') else None
        best_ask = Decimal(str(ticker['ask'])) if ticker.get('ask') else None
        price = calculate_mid_price(best_bid, best_ask, last_price)
        
        return FuturesData(
            price=price,
            index_price=index_price,
            mark_price=mark_price,
            funding_rate=funding_rate,
            funding_interval=funding_interval,
        )
    
    async def close(self):
        """Close exchange connections and httpx client"""
        await super().close()
        if self._httpx_client:
            await self._httpx_client.aclose()
            self._httpx_client = None


class GateCollector(CcxtCollector):
    def __init__(self, cex_id: int = 4, config: Optional[Dict] = None):
        super().__init__(cex_id, 'gate', config)
    
    async def get_futures_price(self, symbol: str) -> FuturesData:
        """
        Fetch futures data for Gate with funding interval
        Price = (bid + ask) / 2 if both valid, else last price
        """
        ccxt_symbol = unified_to_ccxt_swap_symbol(symbol)
        
        # Fetch ticker data
        ticker = await self.futures_exchange.fetch_ticker(ccxt_symbol)
        
        # Debug: log raw ticker data
        if os.getenv('DEBUG_TICKER'):
            logger.warning(f"[gate] FUTURES ticker for {symbol}: {ticker}")
        
        # Fetch funding rate and interval
        funding_rate = None
        funding_interval = None
        try:
            funding_info = await self.futures_exchange.fetch_funding_rate(ccxt_symbol)
            funding_rate = Decimal(str(funding_info['fundingRate'])) if funding_info.get('fundingRate') else None
            
            # Try to get interval directly from raw info first (Gate returns funding_interval in seconds)
            if funding_info.get('info'):
                info = funding_info['info']
                if info.get('funding_interval'):
                    interval_secs = int(info['funding_interval'])
                    interval_hours = interval_secs // 3600
                    funding_interval = f"{interval_hours}h"
            
            # Fallback: calculate from timestamps if no direct value
            if not funding_interval and funding_info.get('fundingTimestamp') and funding_info.get('nextFundingTimestamp'):
                interval_ms = funding_info['nextFundingTimestamp'] - funding_info['fundingTimestamp']
                interval_hours = interval_ms // (1000 * 60 * 60)
                funding_interval = f"{interval_hours}h"
        except Exception as e:
            print(f"[gate] Failed to fetch funding info: {e}")
        
        # Get mark/index price from ticker info
        mark_price = None
        index_price = None
        if ticker.get('info'):
            info = ticker['info']
            if info.get('mark_price'):
                mark_price = Decimal(str(info['mark_price']))
            if info.get('index_price'):
                index_price = Decimal(str(info['index_price']))
        
        # Parse bid/ask/last and calculate mid price
        last_price = Decimal(str(ticker['last'])) if ticker.get('last') else None
        best_bid = Decimal(str(ticker['bid'])) if ticker.get('bid') else None
        best_ask = Decimal(str(ticker['ask'])) if ticker.get('ask') else None
        price = calculate_mid_price(best_bid, best_ask, last_price)
        
        return FuturesData(
            price=price,
            index_price=index_price,
            mark_price=mark_price,
            funding_rate=funding_rate,
            funding_interval=funding_interval,
        )


class KrakenCollector(CcxtCollector):
    """
    Kraken collector with separate futures exchange (krakenfutures).
    Kraken spot and futures are different platforms in CCXT.
    """
    def __init__(self, cex_id: int = 5, config: Optional[Dict] = None):
        super().__init__(cex_id, 'kraken', config)
        
        # Override futures_exchange with krakenfutures (separate platform)
        futures_config = config.copy() if config else {}
        futures_config['enableRateLimit'] = True
        futures_config['options'] = {'defaultType': 'swap'}
        self.futures_exchange = ccxt.krakenfutures(futures_config)
    
    async def get_futures_price(self, symbol: str) -> FuturesData:
        """
        Fetch futures data for Kraken Futures.
        Price = (bid + ask) / 2 if both valid, else markPrice (Kraken has no last price)
        Funding interval is 1 hour for all Kraken perpetuals.
        """
        ccxt_symbol = unified_to_ccxt_swap_symbol(symbol)
        
        # Fetch ticker data
        ticker = await self.futures_exchange.fetch_ticker(ccxt_symbol)
        info = ticker.get('info', {})
        
        # Debug: log raw ticker data
        if os.getenv('DEBUG_TICKER'):
            logger.warning(f"[kraken] FUTURES ticker for {symbol}: {ticker}")
        
        # Get markPrice and indexPrice
        mark_price = None
        index_price = None
        
        if info.get('markPrice'):
            try:
                mark_price = Decimal(str(info['markPrice']))
            except:
                pass
        
        if info.get('indexPrice'):
            try:
                index_price = Decimal(str(info['indexPrice']))
            except:
                pass
        
        # Get funding rate (already in decimal format)
        funding_rate = None
        if info.get('fundingRate'):
            try:
                funding_rate = Decimal(str(info['fundingRate']))
            except:
                pass
        
        # Parse bid/ask/last and calculate mid price (fallback to markPrice if no last)
        best_bid = Decimal(str(ticker['bid'])) if ticker.get('bid') else None
        best_ask = Decimal(str(ticker['ask'])) if ticker.get('ask') else None
        price = calculate_mid_price(best_bid, best_ask, mark_price)
        
        return FuturesData(
            price=price,
            index_price=index_price,
            mark_price=mark_price,
            funding_rate=funding_rate,
            funding_interval='1h',  # Kraken Futures: 1 hour funding interval
        )


class AsterCollector(CcxtCollector):
    """
    Aster collector with custom mark/index price fetching via httpx
    (CCXT's fetch_mark_price is not implemented for Aster)
    """
    def __init__(self, cex_id: int = 6, config: Optional[Dict] = None):
        super().__init__(cex_id, 'aster', config)
        self._httpx_client = None
    
    async def _get_httpx_client(self):
        """Lazy initialization of httpx client"""
        if self._httpx_client is None:
            self._httpx_client = httpx.AsyncClient(timeout=10.0)
        return self._httpx_client
    
    async def get_spot_price(self, symbol: str, **kwargs) -> SpotData:
        """
        Fetch spot price for Aster
        Price = (bid + ask) / 2 if both valid, else last price
        Custom implementation to properly handle bid/ask when API returns 0
        """
        ccxt_symbol = unified_to_ccxt_symbol(symbol)
        
        # Fetch ticker data
        ticker = await self.spot_exchange.fetch_ticker(ccxt_symbol)
        
        # Debug: log raw ticker data
        if os.getenv('DEBUG_TICKER'):
            logger.warning(f"[aster] SPOT ticker for {symbol}: {ticker}")
        
        # Get raw info for bid/ask (CCXT may convert 0 to None)
        info = ticker.get('info', {})
        
        # Parse bid/ask from raw API response, preserving 0 values
        best_bid = None
        best_ask = None
        
        if info.get('bidPrice') is not None:
            try:
                bid_val = Decimal(str(info['bidPrice']))
                best_bid = bid_val if bid_val > 0 else Decimal('0')
            except:
                pass
        
        if info.get('askPrice') is not None:
            try:
                ask_val = Decimal(str(info['askPrice']))
                best_ask = ask_val if ask_val > 0 else Decimal('0')
            except:
                pass
        
        # Calculate mid price
        last_price = Decimal(str(ticker['last'])) if ticker.get('last') else None
        price = calculate_mid_price(best_bid, best_ask, last_price)
        
        return SpotData(
            price=price,
            best_bid=best_bid,
            best_ask=best_ask,
        )
    
    async def get_futures_price(self, symbol: str) -> FuturesData:
        """
        Fetch futures/perpetual price data for Aster
        Price = (bid + ask) / 2 if both valid, else last price
        Uses httpx to fetch mark/index prices from premiumIndex endpoint
        """
        ccxt_symbol = unified_to_ccxt_swap_symbol(symbol)
        parts = symbol.upper().split('_')
        aster_symbol = f"{parts[0]}{parts[1]}" if len(parts) == 2 else symbol.replace('/', '').replace(':', '')
        
        # Define async tasks
        async def fetch_ticker():
            return await self.futures_exchange.fetch_ticker(ccxt_symbol)
        
        async def fetch_funding():
            try:
                return await self.futures_exchange.fetch_funding_rate(ccxt_symbol)
            except Exception as e:
                print(f"[{self.cex_name}] Failed to fetch funding rate for {symbol}: {e}")
                return None
        
        async def fetch_premium_index():
            try:
                client = await self._get_httpx_client()
                resp = await client.get(f"https://fapi.asterdex.com/fapi/v1/premiumIndex?symbol={aster_symbol}")
                return resp.json() if resp.status_code == 200 else None
            except Exception:
                return None
        
        async def fetch_funding_info():
            try:
                client = await self._get_httpx_client()
                resp = await client.get("https://fapi.asterdex.com/fapi/v1/fundingInfo")
                return resp.json() if resp.status_code == 200 else None
            except Exception:
                return None
        
        # Execute all requests in parallel
        ticker, funding_info, premium_data, funding_info_data = await asyncio.gather(
            fetch_ticker(), fetch_funding(), fetch_premium_index(), fetch_funding_info()
        )
        
        # Debug: log raw ticker data
        if os.getenv('DEBUG_TICKER'):
            logger.warning(f"[aster] FUTURES ticker for {symbol}: {ticker}")
        
        # Parse funding rate
        funding_rate = None
        if funding_info and funding_info.get('fundingRate'):
            funding_rate = Decimal(str(funding_info['fundingRate']))
        
        # Parse mark/index from premium index
        mark_price = None
        index_price = None
        if premium_data:
            mark_price = Decimal(str(premium_data['markPrice'])) if premium_data.get('markPrice') else None
            index_price = Decimal(str(premium_data['indexPrice'])) if premium_data.get('indexPrice') else None
        
        # Parse funding interval
        funding_interval = None
        if funding_info_data:
            for item in funding_info_data:
                if item.get('symbol') == aster_symbol and item.get('fundingIntervalHours'):
                    funding_interval = f"{item['fundingIntervalHours']}h"
                    break
        
        # Parse bid/ask/last and calculate mid price
        last_price = Decimal(str(ticker['last'])) if ticker.get('last') else None
        best_bid = Decimal(str(ticker['bid'])) if ticker.get('bid') else None
        best_ask = Decimal(str(ticker['ask'])) if ticker.get('ask') else None
        price = calculate_mid_price(best_bid, best_ask, last_price)
        
        return FuturesData(
            price=price,
            index_price=index_price,
            mark_price=mark_price,
            funding_rate=funding_rate,
            funding_interval=funding_interval,
        )
    
    async def get_price_precision(self, symbol: str) -> Optional[int]:
        """
        Get price precision for Aster using httpx
        (Custom implementation since CCXT may not have full market info for Aster)
        """
        try:
            parts = symbol.upper().split('_')
            aster_symbol = f"{parts[0]}{parts[1]}" if len(parts) == 2 else symbol
            
            client = await self._get_httpx_client()
            resp = await client.get("https://fapi.asterdex.com/fapi/v1/exchangeInfo")
            
            if resp.status_code == 200:
                data = resp.json()
                for sym_info in data.get('symbols', []):
                    if sym_info.get('symbol') == aster_symbol:
                        # Find price precision from filters
                        for f in sym_info.get('filters', []):
                            if f.get('filterType') == 'PRICE_FILTER' and f.get('tickSize'):
                                tick_size = f['tickSize']
                                # Count decimal places in tick size
                                if '.' in tick_size:
                                    decimal_part = tick_size.rstrip('0').split('.')[1]
                                    return len(decimal_part)
                                return 0
                        # Fallback to pricePrecision
                        if sym_info.get('pricePrecision'):
                            return int(sym_info['pricePrecision'])
        except Exception as e:
            print(f"[{self.cex_name}] Failed to get price precision for {symbol}: {e}")
        
        return None
    
    async def close(self):
        """Close exchange and httpx connections"""
        await super().close()
        if self._httpx_client:
            await self._httpx_client.aclose()
            self._httpx_client = None


class BinanceAlphaCollector(CexBase):
    """
    Binance Alpha collector - uses direct API calls (not supported by CCXT)
    API Docs: https://developers.binance.com/docs/alpha/market-data/rest-api
    
    Note: Binance Alpha only has spot trading, no futures
    
    Symbol format: 
    - Input: gorilla_usdt (token symbol + quote)
    - API: ALPHA_175USDT (alphaId + quote)
    """
    
    BASE_URL = "https://www.binance.com/bapi/defi/v1/public/alpha-trade"
    TOKEN_LIST_URL = "https://www.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/cex/alpha/all/token/list"
    
    def __init__(self, cex_id: int = 7, config: Optional[Dict] = None):
        super().__init__(cex_id, 'alpha')
        self._httpx_client = None
        self._config = config or {}
        self._exchange_info_cache = None
        self._token_list_cache = None  # symbol -> token info mapping
    
    async def _get_httpx_client(self):
        """Lazy initialization of httpx client with optional proxy"""
        if self._httpx_client is None:
            # Support proxy configuration
            proxies = self._config.get('proxies')
            if proxies:
                proxy_url = proxies.get('https') or proxies.get('http')
                self._httpx_client = httpx.AsyncClient(
                    timeout=10.0,
                    proxy=proxy_url
                )
            else:
                self._httpx_client = httpx.AsyncClient(timeout=10.0)
        return self._httpx_client
    
    async def _load_token_list(self) -> Dict[str, dict]:
        """
        Load token list from Binance Alpha API and cache it
        Returns: dict mapping lowercase symbol to token info
        API: https://developers.binance.com/docs/alpha/market-data/rest-api/token-list
        """
        if self._token_list_cache is not None:
            return self._token_list_cache
        
        try:
            client = await self._get_httpx_client()
            resp = await client.get(self.TOKEN_LIST_URL)
            
            if resp.status_code == 200:
                result = resp.json()
                if result.get('success') and result.get('data'):
                    # Build symbol -> token info mapping
                    self._token_list_cache = {}
                    for token in result['data']:
                        symbol = token.get('symbol', '').lower()
                        if symbol:
                            self._token_list_cache[symbol] = {
                                'alphaId': token.get('alphaId'),  # e.g., "ALPHA_175"
                                'name': token.get('name'),
                                'decimals': token.get('decimals'),
                                'tradeDecimal': token.get('tradeDecimal'),
                                'chainId': token.get('chainId'),
                                'contractAddress': token.get('contractAddress'),
                                'price': token.get('price'),
                            }
                    print(f"[alpha] Loaded {len(self._token_list_cache)} tokens")
                    return self._token_list_cache
        except Exception as e:
            print(f"[alpha] Failed to load token list: {e}")
        
        self._token_list_cache = {}
        return self._token_list_cache
    
    async def get_alpha_id(self, symbol: str) -> Optional[str]:
        """
        Convert token symbol to alphaId
        e.g., "gorilla" -> "ALPHA_175"
        
        Args:
            symbol: Token symbol (e.g., "gorilla")
        Returns:
            alphaId string (e.g., "ALPHA_175") or None if not found
        """
        token_list = await self._load_token_list()
        token_info = token_list.get(symbol.lower())
        if token_info:
            return token_info.get('alphaId')
        return None
    
    async def get_token_info(self, symbol: str) -> Optional[dict]:
        """
        Get full token info by symbol
        
        Args:
            symbol: Token symbol (e.g., "gorilla")
        Returns:
            Token info dict or None if not found
        """
        token_list = await self._load_token_list()
        return token_list.get(symbol.lower())
    
    async def _convert_symbol(self, symbol: str) -> str:
        """
        Convert unified symbol to Binance Alpha API format
        
        Input formats supported:
        - gorilla_usdt -> looks up alphaId -> ALPHA_175USDT
        - 175_usdt -> ALPHA_175USDT (direct alphaId number)
        
        Returns: API format like "ALPHA_175USDT"
        """
        parts = symbol.upper().split('_')
        if len(parts) != 2:
            return symbol.upper()
        
        base, quote = parts[0], parts[1]
        
        # Check if base is already an alphaId number (e.g., "175")
        if base.isdigit():
            return f"ALPHA_{base}{quote}"
        
        # Otherwise look up the symbol to get alphaId
        alpha_id = await self.get_alpha_id(base)
        if alpha_id:
            # alphaId is like "ALPHA_175", extract the number
            alpha_num = alpha_id.replace('ALPHA_', '')
            return f"ALPHA_{alpha_num}{quote}"
        
        # Fallback: use base as-is
        print(f"[alpha] Warning: Could not find alphaId for symbol '{base}'")
        return f"ALPHA_{base}{quote}"
    
    async def get_spot_price(self, symbol: str, alpha_id: str = None) -> SpotData:
        """
        Fetch spot price from Binance Alpha ticker API
        Note: Binance Alpha API doesn't provide bid/ask, only lastPrice
        
        Args:
            symbol: Unified symbol (e.g., "gorilla_usdt" or "175_usdt")
            alpha_id: Optional pre-configured alphaId (e.g., "ALPHA_175") to skip lookup
        """
        client = await self._get_httpx_client()
        
        # Use pre-configured alpha_id if provided (avoids token list lookup)
        if alpha_id:
            parts = symbol.upper().split('_')
            quote = parts[1] if len(parts) == 2 else 'USDT'
            alpha_num = alpha_id.replace('ALPHA_', '')
            alpha_symbol = f"ALPHA_{alpha_num}{quote}"
        else:
            alpha_symbol = await self._convert_symbol(symbol)
        
        try:
            resp = await client.get(
                f"{self.BASE_URL}/ticker",
                params={"symbol": alpha_symbol}
            )
            
            if resp.status_code == 200:
                result = resp.json()
                
                # Debug: log raw ticker data
                if os.getenv('DEBUG_TICKER'):
                    logger.warning(f"[alpha] SPOT ticker for {symbol}: {result}")
                
                if result.get('success') and result.get('data'):
                    data = result['data']
                    # Binance Alpha only provides lastPrice, no bid/ask
                    return SpotData(
                        price=Decimal(str(data['lastPrice'])) if data.get('lastPrice') else None,
                        best_bid=None,
                        best_ask=None,
                    )
            
            print(f"[alpha] Failed to get ticker for {symbol} ({alpha_symbol}): {resp.status_code}")
            return SpotData()
            
        except Exception as e:
            print(f"[alpha] Error fetching spot price for {symbol}: {e}")
            return SpotData()
    
    async def get_futures_price(self, symbol: str) -> FuturesData:
        """
        Binance Alpha doesn't have futures trading
        Returns empty FuturesData
        """
        return FuturesData()
    
    async def get_price_precision(self, symbol: str) -> Optional[int]:
        """
        Get price precision from token list
        """
        try:
            parts = symbol.split('_')
            if len(parts) >= 1:
                base = parts[0]
                # If it's a number (alphaId), we can't look up easily
                if not base.isdigit():
                    token_info = await self.get_token_info(base)
                    if token_info and token_info.get('tradeDecimal'):
                        return int(token_info['tradeDecimal'])
        except Exception as e:
            print(f"[alpha] Failed to get price precision for {symbol}: {e}")
        
        return 8  # Default precision for Binance Alpha
    
    async def close(self):
        """Close httpx client"""
        if self._httpx_client:
            await self._httpx_client.aclose()
            self._httpx_client = None


def create_cex_collector(exchange_name: str, exchange_id: int, config: Optional[Dict] = None) -> CexBase:
    """
    Factory function to create a CEX collector
    Args:
        exchange_name: Exchange name (lowercase)
        exchange_id: Exchange ID
        config: Optional config dict
    Returns:
        CexBase instance (CcxtCollector or custom collector)
    """
    collectors = {
        'binance': BinanceCollector,
        'bitget': BitgetCollector,
        'bybit': BybitCollector,
        'okx': OkxCollector,
        'gate': GateCollector,
        'kraken': KrakenCollector,
        'aster': AsterCollector,
        'alpha': BinanceAlphaCollector,
    }
    
    exchange_lower = exchange_name.lower()
    if exchange_lower not in collectors:
        raise ValueError(f"Unknown exchange: {exchange_name}")
    
    return collectors[exchange_lower](cex_id=exchange_id, config=config)
