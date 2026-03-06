"""
Database maintenance script
- Cleanup old partitions (default: keep 3 months)
- Run via cron: 0 0 1 * * python maintenance.py (每月1号执行)
"""
import asyncio
import logging
import os
import sys

from config import DatabaseConfig
from db.database import Database

log_level = logging.DEBUG if os.getenv('DEBUG') else logging.INFO
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


async def cleanup_partitions(months_to_keep: int = 3):
    """Delete old historical partitions"""
    db = Database(DatabaseConfig())
    
    try:
        await db.connect()
        await db.init_tables()
        
        logger.info(f"Cleaning up partitions older than {months_to_keep} months...")
        result = await db.cleanup_old_partitions(months_to_keep)
        
        print(result)
        logger.info("Cleanup completed")
        
    finally:
        await db.close()


if __name__ == '__main__':
    months = 3
    
    if len(sys.argv) > 1:
        if sys.argv[1] in ['-h', '--help']:
            print("Usage: python maintenance.py [months_to_keep]")
            print("  months_to_keep: Number of months to retain (default: 3)")
            print("\nExample:")
            print("  python maintenance.py      # Keep 3 months")
            print("  python maintenance.py 6    # Keep 6 months")
            sys.exit(0)
        else:
            months = int(sys.argv[1])
    
    asyncio.run(cleanup_partitions(months))
