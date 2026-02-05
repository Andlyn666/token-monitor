"""
Test script for CEX collectors using CCXT

If you're in China or behind a firewall, you may need to use a proxy.
Set environment variables:
    export HTTP_PROXY=http://127.0.0.1:7890
    export HTTPS_PROXY=http://127.0.0.1:7890

Or pass proxy config to collectors (see below).
"""
import asyncio
import os
import sys
sys.path.insert(0, '.')

from cex.ccxt_collector import (
    BinanceCollector,
    OkxCollector,
    BybitCollector,
    BitgetCollector,
    GateCollector,
    AsterCollector,
    BinanceAlphaCollector,
    CcxtCollector,
)
from cex.cex_base import format_price


def get_proxy_config():
    """Get proxy configuration from environment"""
    proxy = os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY')
    if proxy:
        print(f"Using proxy: {proxy}")
        return {
            'proxies': {
                'http': proxy,
                'https': proxy,
            },
            'aiohttp_proxy': proxy,
        }
    return {}


async def test_exchange(collector: CcxtCollector, name: str, symbol: str = 'rave_usd1', futures_only: bool = False):
    """Test a single exchange"""
    print(f"\n{'='*50}")
    print(f"Testing {name} - {symbol.upper()}")
    print('='*50)
    
    try:
        # Get price precision first
        print(f"\n[{name}] Fetching price precision for {symbol}...")
        precision = await collector.get_price_precision(symbol)
        print(f"  {symbol.upper()} Precision: {precision} decimals")
        
        if not futures_only:
            # Test spot price
            print(f"\n[{name}] Fetching {symbol} spot price...")
            spot_data = await collector.get_spot_price(symbol)
            print(f"  Spot Price (raw):       {spot_data.price}")
            if precision is not None and spot_data.price is not None:
                print(f"  Spot Price (formatted): {format_price(spot_data.price, precision)}")
            print(f"  Best Bid (raw):         {spot_data.best_bid}")
            if precision is not None and spot_data.best_bid is not None:
                print(f"  Best Bid (formatted):   {format_price(spot_data.best_bid, precision)}")
            print(f"  Best Ask (raw):         {spot_data.best_ask}")
            if precision is not None and spot_data.best_ask is not None:
                print(f"  Best Ask (formatted):   {format_price(spot_data.best_ask, precision)}")
        
        # Test futures price
        print(f"\n[{name}] Fetching {symbol} futures price...")
        futures_data = await collector.get_futures_price(symbol)
        print(f"  Futures Price (raw):       {futures_data.price}")
        if precision is not None and futures_data.price is not None:
            print(f"  Futures Price (formatted): {format_price(futures_data.price, precision)}")
        print(f"  Index Price (raw):         {futures_data.index_price}")
        if precision is not None and futures_data.index_price is not None:
            print(f"  Index Price (formatted):   {format_price(futures_data.index_price, precision)}")
        print(f"  Mark Price (raw):          {futures_data.mark_price}")
        if precision is not None and futures_data.mark_price is not None:
            print(f"  Mark Price (formatted):    {format_price(futures_data.mark_price, precision)}")
        print(f"  Funding Rate: {futures_data.funding_rate}")
        print(f"  Funding Interval: {futures_data.funding_interval}")
        
        # Test full data (using new signature with base_token, spot_symbol, fut_symbol)
        base_token = symbol.split('_')[0] if '_' in symbol else symbol
        print(f"\n[{name}] Fetching full price data (base={base_token}, spot={symbol if not futures_only else None}, fut={symbol})...")
        full_data = await collector.get_price_data(
            base_token=base_token,
            spot_symbol=symbol if not futures_only else None,
            fut_symbol=symbol
        )
        print(f"  Base Token: {full_data.base_token}")
        print(f"  Spot Symbol: {full_data.spot_symbol}")
        print(f"  Fut Symbol: {full_data.fut_symbol}")
        print(f"  CEX ID: {full_data.cex}")
        print(f"  Timestamp: {full_data.timestamp}")
        if full_data.spot:
            print(f"  Spot (raw):       {full_data.spot.price}")
            if precision is not None and full_data.spot.price is not None:
                print(f"  Spot (formatted): {format_price(full_data.spot.price, precision)}")
        if full_data.futures:
            print(f"  Futures (raw):       {full_data.futures.price}")
            if precision is not None and full_data.futures.price is not None:
                print(f"  Futures (formatted): {format_price(full_data.futures.price, precision)}")
        
        print(f"\n[{name}] SUCCESS!")
        return True
        
    except Exception as e:
        import traceback
        print(f"\n[{name}] ERROR: {type(e).__name__}: {e}")
        print(f"\nPossible causes:")
        print(f"  1. Network issue - exchange API may be blocked in your region")
        print(f"  2. Need proxy - set HTTP_PROXY/HTTPS_PROXY environment variables")
        print(f"  3. Rate limited - wait and try again")
        print(f"  4. Symbol {symbol} may not exist on this exchange")
        print(f"\nFull traceback:")
        traceback.print_exc()
        return False
    
    finally:
        await collector.close()


async def debug_aster_spot(symbol: str = 'rave_usd1'):
    """Debug Aster spot API to check bid/ask values"""
    import httpx
    from cex.ccxt_collector import unified_to_ccxt_symbol
    
    print(f"\n{'='*60}")
    print(f"DEBUG: Aster Spot API for {symbol}")
    print('='*60)
    
    proxy_config = get_proxy_config()
    collector = AsterCollector(config=proxy_config)
    
    try:
        # 1. Test CCXT fetch_ticker
        ccxt_symbol = unified_to_ccxt_symbol(symbol)
        print(f"\n[1] CCXT fetch_ticker for {ccxt_symbol}")
        print("-" * 40)
        
        ticker = await collector.spot_exchange.fetch_ticker(ccxt_symbol)
        print(f"  Raw ticker keys: {list(ticker.keys())}")
        print(f"  last: {ticker.get('last')}")
        print(f"  bid: {ticker.get('bid')}")
        print(f"  ask: {ticker.get('ask')}")
        print(f"  bidVolume: {ticker.get('bidVolume')}")
        print(f"  askVolume: {ticker.get('askVolume')}")
        print(f"  high: {ticker.get('high')}")
        print(f"  low: {ticker.get('low')}")
        print(f"  info (raw API response): {ticker.get('info')}")
        
        # 2. Test direct Aster Spot API (ticker/24hr)
        parts = symbol.upper().split('_')
        aster_symbol = f"{parts[0]}{parts[1]}" if len(parts) == 2 else symbol
        
        print(f"\n[2] Direct Aster Spot API - /api/v1/ticker/24hr for {aster_symbol}")
        print("-" * 40)
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://sapi.asterdex.com/api/v1/ticker/24hr?symbol={aster_symbol}")
            print(f"  Status: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                print(f"  Raw response: {data}")
        
        # 3. Test direct Aster Spot API (ticker/bookTicker for bid/ask)
        print(f"\n[3] Direct Aster Spot API - /api/v1/ticker/bookTicker for {aster_symbol}")
        print("-" * 40)
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://sapi.asterdex.com/api/v1/ticker/bookTicker?symbol={aster_symbol}")
            print(f"  Status: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                print(f"  Raw response: {data}")
                print(f"  bidPrice: {data.get('bidPrice')}")
                print(f"  bidQty: {data.get('bidQty')}")
                print(f"  askPrice: {data.get('askPrice')}")
                print(f"  askQty: {data.get('askQty')}")
        
        # 4. Test CCXT fetch_order_book
        print(f"\n[4] CCXT fetch_order_book for {ccxt_symbol}")
        print("-" * 40)
        
        try:
            orderbook = await collector.spot_exchange.fetch_order_book(ccxt_symbol, limit=5)
            print(f"  bids (top 5): {orderbook.get('bids', [])[:5]}")
            print(f"  asks (top 5): {orderbook.get('asks', [])[:5]}")
            if orderbook.get('bids'):
                print(f"  Best bid price: {orderbook['bids'][0][0]}")
            if orderbook.get('asks'):
                print(f"  Best ask price: {orderbook['asks'][0][0]}")
        except Exception as e:
            print(f"  Error: {e}")
        
        # 5. Direct Aster API - /api/v1/depth (orderbook)
        print(f"\n[5] Direct Aster Spot API - /api/v1/depth for {aster_symbol}")
        print("-" * 40)
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://sapi.asterdex.com/api/v1/depth?symbol={aster_symbol}&limit=10")
            print(f"  Status: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                print(f"  bids: {data.get('bids', [])[:5]}")
                print(f"  asks: {data.get('asks', [])[:5]}")
                if data.get('bids'):
                    print(f"  Best bid: price={data['bids'][0][0]}, qty={data['bids'][0][1]}")
                else:
                    print(f"  Best bid: None (no bids)")
                if data.get('asks'):
                    print(f"  Best ask: price={data['asks'][0][0]}, qty={data['asks'][0][1]}")
        
        print(f"\n{'='*60}")
        print("DEBUG COMPLETE")
        print('='*60)
        
    except Exception as e:
        import traceback
        print(f"\nERROR: {e}")
        traceback.print_exc()
    finally:
        await collector.close()


async def debug_binance_alpha(token_symbol: str = 'RAVE', quote: str = 'usdt'):
    """
    Debug Binance Alpha API with symbol lookup
    
    Args:
        token_symbol: Token symbol (e.g., "RAVE", "gorilla")
        quote: Quote currency (default: "usdt")
    """
    import httpx
    
    symbol = f"{token_symbol}_{quote}".lower()
    
    print(f"\n{'='*60}")
    print(f"DEBUG: Binance Alpha API")
    print(f"  Token: {token_symbol}")
    print(f"  Quote: {quote}")
    print(f"  Full symbol: {symbol}")
    print('='*60)
    
    proxy_config = get_proxy_config()
    collector = BinanceAlphaCollector(config=proxy_config)
    
    try:
        # 1. Test token list loading
        print(f"\n[1] Loading Token List")
        print("-" * 40)
        token_list = await collector._load_token_list()
        print(f"  Loaded {len(token_list)} tokens")
        # 2. Test symbol lookup
        print(f"\n[2] Looking up token: {token_symbol}")
        print("-" * 40)
        
        token_info = await collector.get_token_info(token_symbol)
        if token_info:
            print(f"  Found!")
            print(f"    alphaId: {token_info.get('alphaId')}")
            print(f"    decimals: {token_info.get('decimals')}")
            print(f"    tradeDecimal: {token_info.get('tradeDecimal')}")
            print(f"    chainId: {token_info.get('chainId')}")
            print(f"    contract: {token_info.get('contractAddress')}")
        else:
            print(f"  Token '{token_symbol}' not found in list!")
            print(f"  Available tokens containing '{token_symbol.lower()}':")
            matches = [k for k in token_list.keys() if token_symbol.lower() in k]
            for m in matches[:10]:
                print(f"    - {m}: {token_list[m].get('alphaId')}")
            return
        
        # 3. Test symbol conversion
        print(f"\n[3] Symbol conversion")
        print("-" * 40)
        alpha_symbol = await collector._convert_symbol(symbol)
        print(f"  {symbol} -> {alpha_symbol}")
        
        # 4. Test ticker API
        print(f"\n[4] Binance Alpha Ticker API")
        print("-" * 40)
        
        client = await collector._get_httpx_client()
        resp = await client.get(
            f"{collector.BASE_URL}/ticker",
            params={"symbol": alpha_symbol}
        )
        print(f"  Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"  Success: {data.get('success')}")
            if data.get('data'):
                ticker = data['data']
                print(f"  lastPrice: {ticker.get('lastPrice')}")
                print(f"  priceChange: {ticker.get('priceChange')}")
                print(f"  priceChangePercent: {ticker.get('priceChangePercent')}%")
                print(f"  volume: {ticker.get('volume')}")
                print(f"  highPrice: {ticker.get('highPrice')}")
                print(f"  lowPrice: {ticker.get('lowPrice')}")
            else:
                print(f"  No data returned - token may not be tradeable")
        else:
            print(f"  Error: {resp.text[:200]}")
        
        # 5. Test get_spot_price
        print(f"\n[5] Testing collector.get_spot_price('{symbol}')")
        print("-" * 40)
        spot_data = await collector.get_spot_price(symbol)
        print(f"  Price: {spot_data.price}")
        print(f"  Best Bid: {spot_data.best_bid}")
        print(f"  Best Ask: {spot_data.best_ask}")
        
        # 6. Test precision
        print(f"\n[6] Testing get_price_precision('{token_symbol}')")
        print("-" * 40)
        precision = await collector.get_price_precision(token_symbol)
        print(f"  Precision: {precision}")
        
        print(f"\n{'='*60}")
        print("DEBUG COMPLETE")
        print('='*60)
        
    except Exception as e:
        import traceback
        print(f"\nERROR: {e}")
        traceback.print_exc()
    finally:
        await collector.close()


async def main():
    """Main test function"""
    print("="*50)
    print("CEX Collector Test Suite")
    print("="*50)
    
    # Debug Binance Alpha - 直接填写 token symbol
    await debug_binance_alpha('RAVE', 'usdt')
    
    return  # 取消注释以只运行 debug
    
    # Debug Aster spot
    # await debug_aster_spot('rave_usd1')
    
    # Test symbol
    test_symbol = 'rave_usdt'
    
    # Check for proxy
    proxy_config = get_proxy_config()
    if not proxy_config:
        print("\nNo proxy configured.")
        print("If tests fail, try setting proxy:")
        print("  export HTTPS_PROXY=http://127.0.0.1:7890")
    
    print(f"\nTesting symbol: {test_symbol.upper()}")
    
    # Test exchanges
    results = {}
    
    # Test Binance
    # results['binance'] = await test_exchange(
    #     BinanceCollector(config=proxy_config), "binance", test_symbol
    # )
    
    # # Test OKX
    # results['okx'] = await test_exchange(
    #     OkxCollector(config=proxy_config), "okx", test_symbol
    # )
    
    # # Test Bybit
    # results['bybit'] = await test_exchange(
    #     BybitCollector(config=proxy_config), "bybit", test_symbol
    # )
    
    # Test Bitget
    results['bitget'] = await test_exchange(
        BitgetCollector(config=proxy_config), "bitget", test_symbol
    )
    
    # Test Gate
    results['gate'] = await test_exchange(
        GateCollector(config=proxy_config), "gate", test_symbol
    )
    
    # Test Aster (futures only exchange)
    results['aster'] = await test_exchange(
        AsterCollector(config=proxy_config), "aster", test_symbol, futures_only=True
    )
    
    # Summary
    print("\n" + "="*50)
    print("Test Summary")
    print("="*50)
    for exchange, success in results.items():
        status = "PASS" if success else "FAIL"
        print(f"  {exchange}: {status}")
    
    passed = sum(1 for s in results.values() if s)
    total = len(results)
    print(f"\nTotal: {passed}/{total} passed")
    
    if passed < total:
        print("\nTips for failed tests:")
        print("  1. Check if you need a VPN/proxy to access exchange APIs")
        print("  2. Set proxy: export HTTPS_PROXY=http://127.0.0.1:7890")
        print("  3. Some exchanges may be temporarily unavailable")


if __name__ == "__main__":
    asyncio.run(main())
