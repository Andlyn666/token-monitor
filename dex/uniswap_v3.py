import os
import json
import time
import logging
from web3 import Web3
from eth_account import Account
from dotenv import load_dotenv
from dex.dex_base import DexBase
from dex.util import sqrt_ratio_x96_to_price

load_dotenv()
logging.basicConfig(filename='log', level=logging.WARNING)

class UniswapV3Dex(DexBase):
    def __init__(self, pair_address, quote_token_address='0xdAC17F958D2ee523a2206206994597C13D831ec7', web3=None):
        self.pair_address = Web3.to_checksum_address(pair_address)
        self.router_address = Web3.to_checksum_address('0xE592427A0AEce92De3Edee1F18E0157C05861564')  # Uniswap V3 Router
        self.quote_token_address = Web3.to_checksum_address(quote_token_address)
        self.web3 = web3 or Web3(Web3.HTTPProvider(os.environ.get('ETH_RPC')))
        
        # Private key is only needed for swap operations, not for reading prices
        private_key = os.environ.get('ETH_PRIVATE_KEY')
        self.account = Account().from_key(private_key) if private_key else None
        
        # Get ABI directory path (abi folder is inside dex/)
        abi_dir = os.path.join(os.path.dirname(__file__), 'abi')
        
        with open(os.path.join(abi_dir, 'v3_pool_abi.json'), encoding='utf-8') as f:
            V3_POOL_ABI = json.load(f)
        with open(os.path.join(abi_dir, 'v3_router_abi.json'), encoding='utf-8') as f:
            V3_ROUTER_ABI = json.load(f)
        with open(os.path.join(abi_dir, 'erc20_abi.json'), encoding='utf-8') as f:
            ERC20_ABI = json.load(f)
        
        self.pair = self.web3.eth.contract(address=self.pair_address, abi=V3_POOL_ABI)
        self.token0 = self.pair.functions.token0().call()
        self.token1 = self.pair.functions.token1().call()
        self.fee = self.pair.functions.fee().call()
        self.token0_contract = self.web3.eth.contract(address=self.token0, abi=ERC20_ABI)
        self.token1_contract = self.web3.eth.contract(address=self.token1, abi=ERC20_ABI)
        self.token0_decimals = self.token0_contract.functions.decimals().call()
        self.token1_decimals = self.token1_contract.functions.decimals().call()
        self.router_abi = V3_ROUTER_ABI

    def get_price(self):
        slot0 = self.pair.functions.slot0().call()
        sqrtPriceX96 = slot0[0]
        price = sqrt_ratio_x96_to_price(sqrtPriceX96, self.token0_decimals, self.token1_decimals)
        # 如果quote token是token0，返回倒数（token0 per token1）；否则返回正向（token1 per token0）
        if self.quote_token_address == self.token0:
            price_inv = 1 / price if price != 0 else 0
            logging.info(f"Current price (base token per quote token): {price_inv}")
            return price_inv
        else:
            logging.info(f"Current price (quote token per base token): {price}")
            return price

    def swap(self, amount_in, token_in_is0, amount_out_min=0, sqrt_price_limit_x96=0):
        if self.account is None:
            raise ValueError("Private key not configured. Cannot perform swap operations.")
        
        token_in = self.token0 if token_in_is0 else self.token1
        token_out = self.token1 if token_in_is0 else self.token0
        nonce = self.web3.eth.get_transaction_count(self.account.address)
        # 根据 token_in 动态选择 approve 的 token 合约
        approve_contract = self.token0_contract if token_in_is0 else self.token1_contract
        # USDT (TetherToken) 合约要求先将 allowance 设为 0，再设为新值
        current_allowance = approve_contract.functions.allowance(self.account.address, self.router_address).call()
        if current_allowance != 0:
            logging.info(f"Current allowance for router: {current_allowance}, resetting to 0...")
            reset_tx = approve_contract.functions.approve(self.router_address, 0).build_transaction({
                'from': self.account.address,
                'nonce': nonce
            })
            signed_reset = self.web3.eth.account.sign_transaction(reset_tx, self.account.key)
            reset_hash = self.web3.eth.send_raw_transaction(signed_reset.raw_transaction)
            logging.info(f"Reset allowance tx: {reset_hash.hex()}")
            res_reset = self.web3.eth.wait_for_transaction_receipt(reset_hash)
            if res_reset.status == 1:
                logging.info("Allowance reset to 0 succeeded!")
            else:
                logging.info("Allowance reset to 0 failed!")
            nonce += 1
        approve_tx = approve_contract.functions.approve(self.router_address, amount_in).build_transaction({
            'from': self.account.address,
            'nonce': nonce
        })
        signed_approve = self.web3.eth.account.sign_transaction(approve_tx, self.account.key)
        approve_hash = self.web3.eth.send_raw_transaction(signed_approve.raw_transaction)
        logging.info(f"Approve tx: {approve_hash.hex()}")
        res = self.web3.eth.wait_for_transaction_receipt(approve_hash)
        if res.status == 1:
            logging.info("Approve transaction succeeded!")
        else:
            logging.info("Approve transaction failed!")
        fee = self.fee
        params = {
            'tokenIn': token_in,
            'tokenOut': token_out,
            'fee': int(fee),
            'recipient': self.account.address,
            'deadline': int(time.time()) + 1800,
            'amountIn': int(amount_in),
            'amountOutMinimum': int(amount_out_min),
            'sqrtPriceLimitX96': int(sqrt_price_limit_x96)
        }
        router = self.web3.eth.contract(address=self.router_address, abi=self.router_abi)
        swap_tx = router.functions.exactInputSingle(params).build_transaction({
            'from': self.account.address,
            'nonce': nonce + 1,
            'gas': 300000,
            'gasPrice': int(self.web3.eth.gas_price * 1.2)
        })
        signed_swap = self.web3.eth.account.sign_transaction(swap_tx, self.account.key)
        swap_hash = self.web3.eth.send_raw_transaction(signed_swap.raw_transaction)
        logging.info(f"Swap tx: {swap_hash.hex()}")
        receipt = self.web3.eth.wait_for_transaction_receipt(swap_hash)
        if receipt.status == 1:
            logging.info("Swap transaction succeeded!")
        else:
            logging.info("Swap transaction failed!")
        return receipt

# # 主测试函数，放在类定义之外
# if __name__ == "__main__":
#     # 示例地址，请替换为实际 Uniswap V3 合约地址
#     test_pair_address = Web3.to_checksum_address('0x65F53f9edF81B6b4b2a7d40C3Ca56054D4c93b9A')
#     test_amount_in = 10 ** 5  # 示例数量
#     test_token_in_is0 = False
#     test_amount_out_min = 0
#     test_sqrt_price_limit_x96 = 0
#     dex = UniswapV3Dex(test_pair_address)
#     logging.info("Testing get_price:")
#     current_price = dex.get_price()
#     logging.info(f"Current price: {current_price}")
#     logging.info("Testing swap:")
#     swap_receipt = dex.swap(test_amount_in, test_token_in_is0, test_amount_out_min, test_sqrt_price_limit_x96)
#     logging.info(f"Swap receipt: {swap_receipt}")