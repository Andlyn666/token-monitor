from abc import ABC, abstractmethod

class DexBase(ABC):
    @abstractmethod
    def swap(self, amount_in, token_in_is0, amount_out_min=0, sqrt_price_limit_x96=0):
        """swap接口，执行兑换"""
        pass

    @abstractmethod
    def get_price(self):
        """获取当前池价格"""
        pass