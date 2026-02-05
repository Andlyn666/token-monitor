from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional


@dataclass
class SpotData:
    """现货数据"""
    price: Optional[Decimal] = None
    best_bid: Optional[Decimal] = None
    best_ask: Optional[Decimal] = None


@dataclass
class FuturesData:
    """合约数据"""
    price: Optional[Decimal] = None
    index_price: Optional[Decimal] = None
    mark_price: Optional[Decimal] = None
    funding_rate: Optional[Decimal] = None
    funding_interval: Optional[str] = None


@dataclass
class CexPriceData:
    """CEX 价格数据"""
    cex: int                              # 交易所 ID
    base_token: str                       # 基础币标识 (e.g., rave)
    spot_symbol: Optional[str] = None     # 现货交易对 (e.g., rave_usd1)
    fut_symbol: Optional[str] = None      # 合约交易对 (e.g., rave_usdt)
    spot: Optional[SpotData] = None       # 现货数据
    futures: Optional[FuturesData] = None # 合约数据
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


def format_price(price: Optional[Decimal], precision: int) -> Optional[Decimal]:
    """
    按精度格式化价格
    Args:
        price: 原始价格
        precision: 小数位数
    Returns:
        格式化后的价格，保留指定小数位数
    """
    if price is None or precision is None:
        return price
    
    # Create quantize pattern (e.g., precision=2 -> Decimal('0.01'))
    quantize_pattern = Decimal(10) ** -precision
    return price.quantize(quantize_pattern)


class CexBase(ABC):
    """CEX 采集器基类"""
    
    def __init__(self, cex_id: int, cex_name: str):
        self.cex_id = cex_id
        self.cex_name = cex_name

    @abstractmethod
    async def get_spot_price(self, symbol: str) -> SpotData:
        """
        获取现货价格数据
        Args:
            symbol: 统一币对标识 (例如 btc_usdt)
        Returns:
            SpotData: 现货数据
        """
        pass

    @abstractmethod
    async def get_futures_price(self, symbol: str) -> FuturesData:
        """
        获取合约价格数据
        Args:
            symbol: 统一币对标识 (例如 btc_usdt)
        Returns:
            FuturesData: 合约数据
        """
        pass

    async def get_price_data(
        self, 
        base_token: str,
        spot_symbol: str = None, 
        fut_symbol: str = None
    ) -> CexPriceData:
        """
        获取完整价格数据
        Args:
            base_token: 基础币标识 (e.g., rave)
            spot_symbol: 现货交易对 (e.g., rave_usd1)
            fut_symbol: 合约交易对 (e.g., rave_usdt)
        Returns:
            CexPriceData: 完整价格数据
        """
        spot_data = None
        futures_data = None

        if spot_symbol:
            try:
                spot_data = await self.get_spot_price(spot_symbol)
            except Exception as e:
                print(f"[{self.cex_name}] Failed to get spot price for {spot_symbol}: {e}")

        if fut_symbol:
            try:
                futures_data = await self.get_futures_price(fut_symbol)
            except Exception as e:
                print(f"[{self.cex_name}] Failed to get futures price for {fut_symbol}: {e}")

        return CexPriceData(
            cex=self.cex_id,
            base_token=base_token,
            spot_symbol=spot_symbol,
            fut_symbol=fut_symbol,
            spot=spot_data,
            futures=futures_data
        )

    @abstractmethod
    async def close(self):
        """关闭连接"""
        pass
