"""
Task management utility for price monitoring system
Use this to add, list, enable/disable tasks in the database
"""
import asyncio
import argparse

from db.database import Database


async def list_tasks(db: Database, task_type: str = None):
    """List all tasks"""
    async with db.pool.acquire() as conn:
        query = """
            SELECT t.id, t.platform_type, e.name as exchange_name,
                   bt.name as base_token,
                   sqt.name as spot_quote, t.spot_remote_id,
                   fqt.name as fut_quote, t.fut_remote_id,
                   t.update_interval, t.price_precision, t.is_active
            FROM config_monitoring_tasks t
            JOIN exchanges e ON t.exchange_id = e.id
            JOIN tokens bt ON t.base_token_id = bt.id
            LEFT JOIN tokens sqt ON t.spot_quote_token_id = sqt.id
            LEFT JOIN tokens fqt ON t.fut_quote_token_id = fqt.id
        """
        if task_type:
            query += " WHERE t.platform_type = $1 ORDER BY e.name, bt.name"
            rows = await conn.fetch(query, task_type.upper())
        else:
            query += " ORDER BY t.platform_type, e.name, bt.name"
            rows = await conn.fetch(query)
    
    if not rows:
        print("No tasks found.")
        return
    
    print(f"\n{'ID':<5} {'Type':<5} {'Exchange':<12} {'Base':<8} {'Spot':<15} {'Spot Remote':<15} {'Futures':<15} {'Interval':<10} {'Prec':<6} {'Active':<8}")
    print("-" * 130)
    for row in rows:
        spot_str = f"{row['base_token']}_{row['spot_quote']}" if row['spot_quote'] else '-'
        spot_remote = row['spot_remote_id'] if row['spot_remote_id'] else '-'
        fut_str = f"{row['base_token']}_{row['fut_quote']}" if row['fut_quote'] else '-'
        precision = str(row['price_precision']) if row['price_precision'] is not None else '-'
        print(f"{row['id']:<5} {row['platform_type']:<5} {row['exchange_name']:<12} "
              f"{row['base_token']:<8} {spot_str:<15} {spot_remote:<15} {fut_str:<15} "
              f"{row['update_interval']:<10} {precision:<6} {'Yes' if row['is_active'] else 'No':<8}")
    print()


async def add_cex_task(db: Database, exchange: str, base_token: str,
                       spot_quote: str = None, fut_quote: str = None,
                       interval: int = 5):
    """Add a CEX monitoring task with separate spot/futures quote tokens"""
    # Look up exchange
    exchange_info = await db.get_exchange_by_name(exchange)
    if not exchange_info:
        print(f"Error: Unknown exchange '{exchange}'")
        exchanges = await db.get_all_exchanges()
        print(f"Available: {', '.join(e['name'] for e in exchanges)}")
        return
    
    # Look up base token
    base_info = await db.get_token_by_name(base_token)
    if not base_info:
        print(f"Error: Unknown base token '{base_token}'")
        tokens = await db.get_all_tokens()
        print(f"Available: {', '.join(t['name'] for t in tokens)}")
        return
    
    # Extra params for special handling
    extra_params = {}
    
    # Special handling for Binance Alpha: look up alphaId
    if exchange.lower() == 'alpha':
        from cex.ccxt_collector import BinanceAlphaCollector
        import os
        
        # Get proxy config
        proxy = os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY')
        config = {'proxies': {'http': proxy, 'https': proxy}} if proxy else {}
        
        collector = BinanceAlphaCollector(config=config)
        try:
            print(f"Looking up Binance Alpha token: {base_token}...")
            token_info = await collector.get_token_info(base_token)
            if token_info:
                alpha_id = token_info.get('alphaId')
                if alpha_id:
                    # Store alpha_id directly in spot_remote_id (will be set below)
                    extra_params['alpha_decimals'] = token_info.get('tradeDecimal')
                    extra_params['alpha_chain_id'] = token_info.get('chainId')
                    extra_params['alpha_contract'] = token_info.get('contractAddress')
                    print(f"  Found: alphaId={alpha_id}, decimals={token_info.get('tradeDecimal')}")
                else:
                    print(f"Warning: Token '{base_token}' found but no alphaId")
                    alpha_id = None
            else:
                print(f"Warning: Token '{base_token}' not found in Binance Alpha token list")
                print("  The task will be created but may not work correctly.")
                print("  Check available tokens at: https://developers.binance.com/docs/alpha/market-data/rest-api/token-list")
                alpha_id = None
        finally:
            await collector.close()
        
        # For Alpha, only spot is supported (no futures)
        if fut_quote:
            print("Warning: Binance Alpha doesn't support futures. Ignoring --fut-quote")
            fut_quote = None
    else:
        alpha_id = None
    
    # Look up spot quote token (optional)
    spot_quote_id = None
    spot_remote_id = None
    if spot_quote:
        spot_quote_info = await db.get_token_by_name(spot_quote)
        if not spot_quote_info:
            print(f"Error: Unknown spot quote token '{spot_quote}'")
            tokens = await db.get_all_tokens()
            print(f"Available: {', '.join(t['name'] for t in tokens)}")
            return
        spot_quote_id = spot_quote_info['id']
        # For Binance Alpha, use alpha_id as spot_remote_id; otherwise use unified symbol
        if alpha_id:
            spot_remote_id = alpha_id  # e.g., "ALPHA_175"
        else:
            spot_remote_id = f"{base_token}_{spot_quote}".lower()
    
    # Look up futures quote token (optional)
    fut_quote_id = None
    fut_remote_id = None
    if fut_quote:
        fut_quote_info = await db.get_token_by_name(fut_quote)
        if not fut_quote_info:
            print(f"Error: Unknown futures quote token '{fut_quote}'")
            tokens = await db.get_all_tokens()
            print(f"Available: {', '.join(t['name'] for t in tokens)}")
            return
        fut_quote_id = fut_quote_info['id']
        fut_remote_id = f"{base_token}_{fut_quote}".lower()
    
    if not spot_quote_id and not fut_quote_id:
        print("Error: At least one of --spot-quote or --fut-quote must be specified")
        return
    
    task_id = await db.add_task(
        exchange_id=exchange_info['id'],
        base_token_id=base_info['id'],
        platform_type='CEX',
        spot_quote_token_id=spot_quote_id,
        spot_remote_id=spot_remote_id,
        fut_quote_token_id=fut_quote_id,
        fut_remote_id=fut_remote_id,
        extra_params=extra_params if extra_params else None,
        update_interval=interval,
        is_active=True,
    )
    
    spot_str = f"spot={base_token}_{spot_quote}" if spot_quote else "spot=None"
    fut_str = f"fut={base_token}_{fut_quote}" if fut_quote else "fut=None"
    # For Alpha, show the alpha_id stored in spot_remote_id
    extra_str = f", remote_id={spot_remote_id}" if alpha_id else ""
    print(f"Added CEX task: id={task_id}, exchange={exchange}, {spot_str}, {fut_str}{extra_str}")


async def add_dex_task(db: Database, exchange: str, base_token: str, quote_token: str,
                       pool_address: str, interval: int = 5, chain: str = None,
                       base_token_address: str = None, quote_token_address: str = None):
    """Add a DEX monitoring task"""
    # Look up exchange
    exchange_info = await db.get_exchange_by_name(exchange)
    if not exchange_info:
        print(f"Error: Unknown exchange '{exchange}'")
        exchanges = await db.get_all_exchanges()
        print(f"Available: {', '.join(e['name'] for e in exchanges)}")
        return
    
    # Look up tokens
    base_info = await db.get_token_by_name(base_token)
    if not base_info:
        print(f"Error: Unknown base token '{base_token}'")
        tokens = await db.get_all_tokens()
        print(f"Available: {', '.join(t['name'] for t in tokens)}")
        return
    
    quote_info = await db.get_token_by_name(quote_token)
    if not quote_info:
        print(f"Error: Unknown quote token '{quote_token}'")
        tokens = await db.get_all_tokens()
        print(f"Available: {', '.join(t['name'] for t in tokens)}")
        return
    
    extra_params = {}
    if chain:
        extra_params['chain'] = chain
    if base_token_address:
        extra_params['base_token_address'] = base_token_address
    if quote_token_address:
        extra_params['quote_token_address'] = quote_token_address
    
    task_id = await db.add_task(
        exchange_id=exchange_info['id'],
        base_token_id=base_info['id'],
        platform_type='DEX',
        spot_quote_token_id=quote_info['id'],
        spot_remote_id=pool_address,  # For DEX, spot_remote_id is pool address
        extra_params=extra_params,
        update_interval=interval,
        is_active=True,
    )
    print(f"Added DEX task: id={task_id}, exchange={exchange}, symbol={base_token}_{quote_token}, pool={pool_address}")


async def toggle_task(db: Database, task_id: int, enable: bool):
    """Enable or disable a task"""
    await db.update_task_status(task_id, enable)
    status = "enabled" if enable else "disabled"
    print(f"Task {task_id} {status}")


async def delete_task(db: Database, task_id: int):
    """Delete a task"""
    await db.delete_task(task_id)
    print(f"Task {task_id} deleted")


async def show_platforms(db: Database):
    """Show available exchanges and tokens"""
    exchanges = await db.get_all_exchanges()
    tokens = await db.get_all_tokens()
    
    print("\nExchanges:")
    for e in exchanges:
        print(f"  {e['id']}: {e['name']}")
    
    print("\nTokens:")
    for t in tokens:
        print(f"  {t['id']}: {t['name']}")


async def add_exchange(db: Database, id: int, name: str):
    """Add a new exchange"""
    await db.add_exchange(id, name)
    print(f"Added exchange: id={id}, name={name}")


async def add_token(db: Database, id: int, name: str):
    """Add a new token"""
    await db.add_token(id, name)
    print(f"Added token: id={id}, name={name}")


async def list_alpha_tokens(search: str = None):
    """List available Binance Alpha tokens"""
    from cex.ccxt_collector import BinanceAlphaCollector
    import os
    
    # Get proxy config
    proxy = os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY')
    config = {'proxies': {'http': proxy, 'https': proxy}} if proxy else {}
    
    collector = BinanceAlphaCollector(config=config)
    try:
        print("Loading Binance Alpha token list...")
        token_list = await collector._load_token_list()
        
        if not token_list:
            print("Failed to load token list or no tokens available.")
            return
        
        # Filter if search term provided
        if search:
            search_lower = search.lower()
            filtered = {k: v for k, v in token_list.items() 
                       if search_lower in k or search_lower in str(v.get('name', '')).lower()}
        else:
            filtered = token_list
        
        print(f"\n=== Binance Alpha Tokens ({len(filtered)}/{len(token_list)}) ===")
        print(f"{'Symbol':<20} {'AlphaId':<15} {'Decimals':<10} {'Chain':<8} {'Contract':<45}")
        print("-" * 100)
        
        for symbol, info in sorted(filtered.items()):
            alpha_id = info.get('alphaId', '-')
            decimals = str(info.get('tradeDecimal', '-'))
            chain = info.get('chainId', '-')
            contract = info.get('contractAddress', '-')[:42] if info.get('contractAddress') else '-'
            print(f"{symbol:<20} {alpha_id:<15} {decimals:<10} {chain:<8} {contract:<45}")
        
        print(f"\nTo add a task: python manage_tasks.py add-cex alpha <symbol> --spot-quote usdt")
        print(f"Example: python manage_tasks.py add-cex alpha gorilla --spot-quote usdt")
        
    finally:
        await collector.close()


async def show_prices(db: Database, price_type: str = None):
    """Show latest collected prices"""
    if price_type != 'dex':
        # Show CEX prices
        cex_data = await db.get_all_cex_latest()
        if cex_data:
            print("\n=== CEX Latest Prices ===")
            print(f"{'Exchange':<12} {'Base':<8} {'Spot Symbol':<15} {'Spot Price':<15} {'Bid':<12} {'Ask':<12} {'Fut Symbol':<15} {'Fut Price':<15} {'Mark':<15} {'Index':<15} {'Funding':<12}")
            print("-" * 165)
            for row in cex_data:
                spot_sym = row.get('spot_symbol') or '-'
                fut_sym = row.get('fut_symbol') or '-'
                spot_p = str(row.get('spot_price') or '-')[:14]
                bid = str(row.get('best_bid') or '-')[:11]
                ask = str(row.get('best_ask') or '-')[:11]
                fut_p = str(row.get('fut_price') or '-')[:14]
                mark = str(row.get('fut_mark') or '-')[:14]
                index = str(row.get('fut_index') or '-')[:14]
                funding = str(row.get('funding_rate') or '-')[:11]
                print(f"{row['exchange_name']:<12} {row['base_token']:<8} {spot_sym:<15} {spot_p:<15} {bid:<12} {ask:<12} {fut_sym:<15} {fut_p:<15} {mark:<15} {index:<15} {funding:<12}")
        else:
            print("\nNo CEX price data found.")
    
    if price_type != 'cex':
        # Show DEX prices
        dex_data = await db.get_all_dex_latest()
        if dex_data:
            print("\n=== DEX Latest Prices ===")
            print(f"{'Exchange':<15} {'Symbol':<15} {'Pool Address':<45} {'Spot Price':<20}")
            print("-" * 100)
            for row in dex_data:
                print(f"{row['exchange_name']:<15} {row['symbol']:<15} {row['pool_address']:<45} {row.get('spot_price') or '-'}")
        else:
            print("\nNo DEX price data found.")


async def main():
    parser = argparse.ArgumentParser(description='Manage price monitoring tasks')
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List all tasks')
    list_parser.add_argument('--type', choices=['cex', 'dex'], help='Filter by type')
    
    # Add CEX command
    add_cex_parser = subparsers.add_parser('add-cex', help='Add a CEX task')
    add_cex_parser.add_argument('exchange', help='Exchange name (e.g., binance, aster)')
    add_cex_parser.add_argument('base_token', help='Base token (e.g., rave)')
    add_cex_parser.add_argument('--spot-quote', help='Spot quote token (e.g., usd1)')
    add_cex_parser.add_argument('--fut-quote', help='Futures quote token (e.g., usdt)')
    add_cex_parser.add_argument('--interval', type=int, default=5, help='Update interval in seconds')
    
    # Add DEX command
    add_dex_parser = subparsers.add_parser('add-dex', help='Add a DEX task')
    add_dex_parser.add_argument('exchange', help='DEX name (e.g., pancake_v3)')
    add_dex_parser.add_argument('base_token', help='Base token (e.g., rave)')
    add_dex_parser.add_argument('quote_token', help='Quote token (e.g., usdt)')
    add_dex_parser.add_argument('pool', help='Pool contract address')
    add_dex_parser.add_argument('--interval', type=int, default=5, help='Update interval in seconds')
    add_dex_parser.add_argument('--chain', help='Chain name (e.g., bsc, ethereum)')
    add_dex_parser.add_argument('--base-token-address', help='Base token contract address')
    add_dex_parser.add_argument('--quote-token-address', help='Quote token contract address')
    
    # Enable/Disable commands
    enable_parser = subparsers.add_parser('enable', help='Enable a task')
    enable_parser.add_argument('task_id', type=int, help='Task ID')
    
    disable_parser = subparsers.add_parser('disable', help='Disable a task')
    disable_parser.add_argument('task_id', type=int, help='Task ID')
    
    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete a task')
    delete_parser.add_argument('task_id', type=int, help='Task ID')
    
    # Show mappings
    subparsers.add_parser('show-platforms', help='Show available exchanges and tokens')
    
    # Show latest prices
    prices_parser = subparsers.add_parser('prices', help='Show latest collected prices')
    prices_parser.add_argument('--type', choices=['cex', 'dex'], help='Filter by type')
    
    # List Binance Alpha tokens
    alpha_parser = subparsers.add_parser('alpha-tokens', help='List available Binance Alpha tokens')
    alpha_parser.add_argument('--search', help='Search filter for symbol/name')
    
    # Add exchange
    add_ex_parser = subparsers.add_parser('add-exchange', help='Add a new exchange')
    add_ex_parser.add_argument('id', type=int, help='Exchange ID')
    add_ex_parser.add_argument('name', help='Exchange name')
    
    # Add token
    add_tok_parser = subparsers.add_parser('add-token', help='Add a new token')
    add_tok_parser.add_argument('id', type=int, help='Token ID')
    add_tok_parser.add_argument('name', help='Token name')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Handle commands that don't need database
    if args.command == 'alpha-tokens':
        await list_alpha_tokens(args.search)
        return
    
    # Connect to database for other commands
    db = Database()
    await db.connect()
    await db.init_tables()
    
    try:
        if args.command == 'list':
            await list_tasks(db, args.type)
        elif args.command == 'add-cex':
            await add_cex_task(
                db, args.exchange, args.base_token,
                spot_quote=args.spot_quote,
                fut_quote=args.fut_quote,
                interval=args.interval
            )
        elif args.command == 'add-dex':
            await add_dex_task(
                db, args.exchange, args.base_token, args.quote_token, args.pool,
                args.interval, args.chain,
                getattr(args, 'base_token_address', None),
                getattr(args, 'quote_token_address', None)
            )
        elif args.command == 'enable':
            await toggle_task(db, args.task_id, True)
        elif args.command == 'disable':
            await toggle_task(db, args.task_id, False)
        elif args.command == 'delete':
            await delete_task(db, args.task_id)
        elif args.command == 'show-platforms':
            await show_platforms(db)
        elif args.command == 'prices':
            await show_prices(db, args.type)
        elif args.command == 'add-exchange':
            await add_exchange(db, args.id, args.name)
        elif args.command == 'add-token':
            await add_token(db, args.id, args.name)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
