import os
import json
import logging
from web3 import Web3
from dotenv import load_dotenv
from web3.middleware import ExtraDataToPOAMiddleware
from dex.util import sqrt_ratio_x96_to_price
load_dotenv()

logging.basicConfig(level=logging.INFO)

class PancakeV4Dex:
    """
    PancakeSwap V4 DEX collector.
    Note: V4 uses a pool manager contract with pool IDs instead of individual pool contracts.
    The pair_id parameter is the pool ID (bytes32 hex string).
    The pool manager address is a protocol constant.
    """
    # PancakeSwap V4 Pool Manager on BSC
    POOL_MGR_ADDRESS = '0xa0FfB9c1CE1Fe56963B0321B32E7A0302114058b'
    
    def __init__(self, pair_id, quote_token_address='0x55d398326f99059fF775485246999027B3197955', web3=None, base_token_address=None):
        self.pool_mgr_address = Web3.to_checksum_address(self.POOL_MGR_ADDRESS)
        # Convert pair_id string to bytes32
        self.pair_id = Web3.to_bytes(hexstr=pair_id) if pair_id else None
        self.quote_token_address = Web3.to_checksum_address(quote_token_address)
        self.web3 = web3 or Web3(Web3.HTTPProvider(os.environ.get('BSC_RPC')))
        self.web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        
        # Get ABI directory path
        abi_dir = os.path.join(os.path.dirname(__file__), 'abi')
        with open(os.path.join(abi_dir, 'v4_pool_mgr_abi.json')) as f:
            V4_POOL_MGR_ABI = json.load(f)
        with open(os.path.join(abi_dir, 'erc20_abi.json')) as f:
            ERC20_ABI = json.load(f)
        
        self.pool_mgr = self.web3.eth.contract(address=self.pool_mgr_address, abi=V4_POOL_MGR_ABI)
        
        # Token addresses should be passed or derived from pool info
        self.token0 = quote_token_address
        self.token1 = base_token_address or "0x97693439EA2f0ecdeb9135881E49f354656a911c"  # Default, should be overridden
        self.token0_contract = self.web3.eth.contract(address=self.token0, abi=ERC20_ABI)
        self.token1_contract = self.web3.eth.contract(address=self.token1, abi=ERC20_ABI)
        self.token0_decimals = self.token0_contract.functions.decimals().call()
        self.token1_decimals = self.token1_contract.functions.decimals().call()

    def get_price(self):
        slot0 = self.pool_mgr.functions.getSlot0(self.pair_id).call()
        sqrtPriceX96 = slot0[0]
        price = sqrt_ratio_x96_to_price(sqrtPriceX96, self.token0_decimals, self.token1_decimals)
        # 如果quote token是token0，返回price（token1 per token0）；否则返回倒数（token0 per token1）
        if self.quote_token_address == self.token0:
            price_inv = 1 / price if price != 0 else 0
            price_inv = round(price_inv, 6)
            logging.info(f"Current price (base token per quote token): {price_inv}")
            return price_inv
        else:
            price = round(price, 6)
            logging.info(f"Current price (quote token per base token): {price}")
            return price

# if __name__ == "__main__":
#     # 示例地址，请替换为实际 Pancake V3 合约地址
#     pair_address = Web3.to_checksum_address('0x84354592cb82EAc7fac65df4478ED1eEbBa0252c')
#     router_address = Web3.to_checksum_address('0x1b81D678ffb9C0263b24A97847620C99d213eB14')
#     amount_in = 10 ** 13  # 示例数量
#     token_in_is0 = True
#     amount_out_min = 0
#     sqrt_price_limit_x96 = 0
#     dex = PancakeV3Dex(pair_address, router_address)
#     print("Testing get_price:")
#     price = dex.get_price()
#     print(f"Current price: {price}")
#     print("Testing swap:")
#     receipt = dex.swap(amount_in, token_in_is0, amount_out_min, sqrt_price_limit_x96)
#     print(f"Swap receipt: {receipt}")
