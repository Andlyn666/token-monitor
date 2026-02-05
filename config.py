"""
Configuration and mappings for the price monitoring system
"""
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# Platform ID Mappings
# =============================================================================

CEX_MAP = {
    "binance": 0,
    "bitget": 1,
    "bybit": 2,
    "okx": 3,
    "gate": 4,
    "kraken": 5,
    "aster": 6,
    "alpha": 7
}

CEX_MAP_REVERSE = {v: k for k, v in CEX_MAP.items()}

DEX_MAP = {
    "pancake_v3": 8,
    "pancake_v4": 9,
    "uniswap_v3": 2,
    "uniswap_v4": 3,
    "aero_v3": 4,
}

DEX_MAP_REVERSE = {v: k for k, v in DEX_MAP.items()}


# =============================================================================
# Database Configuration
# =============================================================================

@dataclass
class DatabaseConfig:
    host: str = os.getenv("DB_HOST", "localhost")
    port: int = int(os.getenv("DB_PORT", "5432"))
    user: str = os.getenv("DB_USER", "postgres")
    password: str = os.getenv("DB_PASSWORD", "")
    database: str = os.getenv("DB_NAME", "token_monitor")
    min_connections: int = int(os.getenv("DB_MIN_CONN", "5"))
    max_connections: int = int(os.getenv("DB_MAX_CONN", "20"))

    @property
    def dsn(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


# =============================================================================
# Monitoring Task Configuration
# =============================================================================

@dataclass
class CexTask:
    """CEX monitoring task"""
    cex_name: str           # Exchange name (e.g., 'binance')
    symbol: str             # Unified symbol (e.g., 'btc_usdt')
    include_spot: bool = True
    include_futures: bool = True
    interval: int = 5       # Polling interval in seconds

    @property
    def cex_id(self) -> int:
        return CEX_MAP.get(self.cex_name.lower(), -1)


@dataclass
class DexTask:
    """DEX monitoring task"""
    dex_name: str           # DEX name (e.g., 'pancake')
    symbol: str             # Unified symbol (e.g., 'astr_usdt')
    pool_address: str       # Pool contract address
    chain: str              # Chain name (e.g., 'bsc', 'ethereum')
    rpc_url: str            # RPC endpoint
    quote_token: Optional[str] = None  # Quote token address for price calculation
    interval: int = 5       # Polling interval in seconds

    @property
    def dex_id(self) -> int:
        return DEX_MAP.get(self.dex_name.lower(), -1)


@dataclass
class MonitoringConfig:
    """Main monitoring configuration"""
    cex_tasks: List[CexTask] = field(default_factory=list)
    dex_tasks: List[DexTask] = field(default_factory=list)
    
    # Alert settings
    max_failure_count: int = 3  # Trigger alert after N consecutive failures
    
    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


# =============================================================================
# Default Configuration (DEPRECATED - Tasks are now loaded from database)
# =============================================================================
# 
# Task configuration is now stored in the database table: config_monitoring_tasks
# Use manage_tasks.py to add/remove/list tasks:
#
#   python manage_tasks.py list                              # List all tasks
#   python manage_tasks.py add-cex binance btc_usdt          # Add CEX task
#   python manage_tasks.py add-dex pancake_v3 cake_usdt 0x...  # Add DEX task
#   python manage_tasks.py enable <task_id>                  # Enable task
#   python manage_tasks.py disable <task_id>                 # Disable task
#   python manage_tasks.py delete <task_id>                  # Delete task
#


# =============================================================================
# RPC Endpoints
# =============================================================================

RPC_ENDPOINTS = {
    "bsc": os.getenv("BSC_RPC", "https://bsc-dataseed.binance.org/"),
    "ethereum": os.getenv("ETH_RPC", "https://eth.llamarpc.com"),
    "base": os.getenv("BASE_RPC", "https://mainnet.base.org"),
}
