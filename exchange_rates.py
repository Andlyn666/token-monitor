"""
Exchange rate collector - fetches currency to USDT rates
- Fiat currencies (EUR, GBP, etc.): Frankfurter API (ECB rates)
- Crypto currencies: Binance
"""
import asyncio
import logging
import os
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional

import httpx
import ccxt.async_support as ccxt

from config import DatabaseConfig
from db.database import Database

log_level = logging.DEBUG if os.getenv('DEBUG') else logging.WARNING
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# Fiat currencies that use Frankfurter API (EUR/USD rate from ECB)
FIAT_CURRENCIES = {'eur', 'gbp', 'jpy', 'aud', 'cad', 'chf'}


class RateFetcher:
    """
    Fetches exchange rates from multiple sources
    - Fiat: Frankfurter API (free, no API key, ECB rates)
    - Crypto: Binance
    
    Can be used standalone or integrated into collector.py
    """
    
    def __init__(self, proxy: Optional[str] = None):
        self.proxy = proxy
        self.binance: Optional[ccxt.Exchange] = None
        self.http_client: Optional[httpx.AsyncClient] = None
    
    async def init(self):
        """Initialize connections"""
        # Binance for crypto rates
        config = {'enableRateLimit': True}
        if self.proxy:
            config['proxies'] = {'http': self.proxy, 'https': self.proxy}
        self.binance = ccxt.binance(config)
        
        # HTTP client for Frankfurter API (fiat rates)
        self.http_client = httpx.AsyncClient(
            proxy=self.proxy,
            timeout=30.0,
        )
    
    async def close(self):
        """Cleanup resources"""
        if self.binance:
            await self.binance.close()
        if self.http_client:
            await self.http_client.aclose()
    
    async def fetch_rate(self, currency: str) -> Optional[Decimal]:
        """
        Fetch exchange rate for a currency to USDT
        - Fiat currencies: Frankfurter API {CURRENCY}/USD (USD ≈ USDT)
        - Crypto currencies: Binance {CURRENCY}/USDT
        """
        currency_lower = currency.lower()
        currency_upper = currency.upper()
        
        try:
            if currency_lower in FIAT_CURRENCIES:
                return await self._fetch_fiat_rate(currency_upper)
            else:
                return await self._fetch_crypto_rate(currency_upper)
        except Exception as e:
            logger.error(f"Failed to fetch rate for {currency}: {e}")
            return None
    
    async def _fetch_fiat_rate(self, currency: str) -> Optional[Decimal]:
        """Fetch fiat currency rate from Frankfurter API (ECB rates)"""
        url = f"https://api.frankfurter.dev/v1/latest?base={currency}&symbols=USD"
        
        try:
            response = await self.http_client.get(url)
            if response.status_code == 200:
                data = response.json()
                if 'rates' in data and 'USD' in data['rates']:
                    return Decimal(str(data['rates']['USD']))
            else:
                logger.warning(f"Frankfurter API error: {response.status_code}")
        except Exception as e:
            logger.error(f"Frankfurter API error for {currency}: {e}")
        
        return None
    
    async def _fetch_crypto_rate(self, currency: str) -> Optional[Decimal]:
        """Fetch crypto currency rate from Binance"""
        symbol = f"{currency}/USDT"
        
        try:
            ticker = await self.binance.fetch_ticker(symbol)
            if ticker and ticker.get('last'):
                return Decimal(str(ticker['last']))
        except ccxt.BadSymbol:
            logger.warning(f"Symbol {symbol} not found on Binance")
        
        return None


class ExchangeRateCollector:
    """
    Full collector with database integration
    For standalone use or cron jobs
    """
    
    def __init__(self):
        self.fetcher: Optional[RateFetcher] = None
        self.db: Optional[Database] = None
    
    async def init(self):
        """Initialize connections"""
        proxy = os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY')
        
        self.fetcher = RateFetcher(proxy=proxy)
        await self.fetcher.init()
        
        self.db = Database(DatabaseConfig())
        await self.db.connect()
        await self.db.init_tables()
    
    async def close(self):
        """Cleanup resources"""
        if self.fetcher:
            await self.fetcher.close()
        if self.db:
            await self.db.close()
    
    async def fetch_rate(self, currency: str) -> Optional[Decimal]:
        """Fetch rate for a single currency"""
        return await self.fetcher.fetch_rate(currency)
    
    async def update_rates(self) -> Dict[str, Decimal]:
        """Fetch and update all exchange rates from database"""
        currencies = await self.db.get_currencies_to_update()
        
        if not currencies:
            logger.info("No currencies to update in database")
            return {}
        
        rates = {}
        timestamp = datetime.utcnow()
        
        for currency in currencies:
            rate = await self.fetcher.fetch_rate(currency)
            if rate is not None:
                rates[currency] = rate
                await self.db.upsert_exchange_rate(
                    currency=currency,
                    rate_to_usdt=rate,
                    timestamp=timestamp,
                )
                logger.info(f"Updated rate: 1 {currency.upper()} = {rate} USDT")
            else:
                logger.warning(f"Failed to fetch rate for {currency}")
        
        logger.info(f"Updated {len(rates)} exchange rates")
        return rates

    async def add_currency(self, currency: str) -> Optional[Decimal]:
        """Add a new currency to track"""
        currency = currency.lower()
        rate = await self.fetcher.fetch_rate(currency)
        
        if rate is not None:
            await self.db.upsert_exchange_rate(
                currency=currency,
                rate_to_usdt=rate,
            )
            logger.info(f"Added currency: 1 {currency.upper()} = {rate} USDT")
            return rate
        else:
            logger.error(f"Failed to add currency {currency}: rate not available")
            return None


async def main():
    """Main entry point - update existing rates"""
    collector = ExchangeRateCollector()
    
    try:
        await collector.init()
        rates = await collector.update_rates()
        
        if rates:
            print("\n=== Updated Exchange Rates (to USDT) ===")
            for currency, rate in sorted(rates.items()):
                print(f"  {currency.upper():6} = {rate:>12.6f} USDT")
        else:
            print("No currencies to update. Use --add <currency> to add one.")
        print()
        
    finally:
        await collector.close()


async def add_currency(currency: str):
    """Add a new currency to track"""
    collector = ExchangeRateCollector()
    
    try:
        await collector.init()
        rate = await collector.add_currency(currency)
        
        if rate:
            print(f"Added: 1 {currency.upper()} = {rate} USDT")
        else:
            print(f"Failed to add {currency.upper()}")
        
    finally:
        await collector.close()


async def run_scheduler(interval_seconds: int = 3600):
    """Run the rate collector on a schedule (default: every hour)"""
    collector = ExchangeRateCollector()
    
    try:
        await collector.init()
        
        while True:
            try:
                rates = await collector.update_rates()
                logger.info(f"Updated {len(rates)} rates, next update in {interval_seconds}s")
            except Exception as e:
                logger.error(f"Error updating rates: {e}")
            
            await asyncio.sleep(interval_seconds)
    
    finally:
        await collector.close()


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == '--daemon':
            interval = int(sys.argv[2]) if len(sys.argv) > 2 else 3600
            print(f"Starting exchange rate daemon (interval: {interval}s)")
            asyncio.run(run_scheduler(interval))
        
        elif sys.argv[1] == '--add' and len(sys.argv) > 2:
            asyncio.run(add_currency(sys.argv[2]))
        
        else:
            print("Usage:")
            print("  python exchange_rates.py           # Update existing rates")
            print("  python exchange_rates.py --add EUR # Add new currency")
            print("  python exchange_rates.py --daemon  # Run as daemon (1h interval)")
            print("  python exchange_rates.py --daemon 1800  # Custom interval (seconds)")
    else:
        asyncio.run(main())
