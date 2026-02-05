import os
import logging
from web3 import Web3
from eth_account import Account
import time
from dotenv import load_dotenv
import json
from dex.dex_base import DexBase
from dex.util import sqrt_ratio_x96_to_price

load_dotenv()
logging.basicConfig(filename='log', level=logging.INFO)

# ABI directory path
_ABI_DIR = os.path.join(os.path.dirname(__file__), 'abi')

def _load_abi(filename):
    with open(os.path.join(_ABI_DIR, filename)) as f:
        return json.load(f)

class AerodromeV3Dex(DexBase):
    def __init__(self, pair_address, quote_token_address='0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913', web3=None):
        self.pair_address = Web3.to_checksum_address(pair_address)
        self.router_address = Web3.to_checksum_address('0xBE6D8f0d05cC4be24d5167a3eF062215bE6D18a5')  # Aerodrome V3 Router
        self.quote_token_address = Web3.to_checksum_address(quote_token_address)
        self.web3 = web3 or Web3(Web3.HTTPProvider(os.environ.get('BASE_RPC')))
        
        # Private key is only needed for swap operations, not for reading prices
        private_key = os.environ.get('BASE_PRIVATE_KEY')
        self.account = Account().from_key(private_key) if private_key else None
        
        # Load ABIs
        AERO_POOL_ABI = _load_abi('aero_pool_abi.json')
        AERO_ROUTER_ABI = _load_abi('aero_router_abi.json')
        ERC20_ABI = _load_abi('erc20_abi.json')
        
        self.pair = self.web3.eth.contract(address=self.pair_address, abi=AERO_POOL_ABI)
        self.token0 = self.pair.functions.token0().call()
        self.token1 = self.pair.functions.token1().call()
        self.tick_spacing = self.pair.functions.tickSpacing().call()
        self.token0_contract = self.web3.eth.contract(address=self.token0, abi=ERC20_ABI)
        self.token1_contract = self.web3.eth.contract(address=self.token1, abi=ERC20_ABI)
        self.token0_decimals = self.token0_contract.functions.decimals().call()
        self.token1_decimals = self.token1_contract.functions.decimals().call()
        self.router_abi = AERO_ROUTER_ABI

    def get_price(self):
        slot0 = self.pair.functions.slot0().call()
        sqrtPriceX96 = slot0[0]
        price = sqrt_ratio_x96_to_price(sqrtPriceX96, self.token0_decimals, self.token1_decimals)
        # 如果quote token是token0，返回price（token1 per token0）；否则返回倒数（token0 per token1）
        if self.quote_token_address == self.token0:
            price_inv = 1 / price if price != 0 else 0
            logging.info(f"Current price (quote token per base token): {price_inv}")
            return round(price_inv, 6)
        else:
            logging.info(f"Current price (base token per quote token): {price}")
            return round(price, 6)

    def swap(self, amount_in, token_in_is0, amount_out_min=0, sqrt_price_limit_x96=0):
        if self.account is None:
            raise ValueError("Private key not configured. Cannot perform swap operations.")
        
        token_in = self.token0 if token_in_is0 else self.token1
        token_out = self.token1 if token_in_is0 else self.token0
        nonce = self.web3.eth.get_transaction_count(self.account.address)
        # 根据 token_in 动态选择 approve 的 token 合约
        approve_contract = self.token0_contract if token_in_is0 else self.token1_contract
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

        # Prepare swap params for exactInputSingle
        params = (
            token_in,           # tokenIn
            token_out,          # tokenOut
            self.tick_spacing,       # tickSpacing (replaces fee)
            self.account.address, # recipient
            int(time.time()) + 1800, # deadline
            amount_in,          # amountIn
            amount_out_min,     # amountOutMinimum
            sqrt_price_limit_x96 # sqrtPriceLimitX96
        )
        router = self.web3.eth.contract(address=self.router_address, abi=self.router_abi)
        swap_tx = router.functions.exactInputSingle(params).build_transaction({
            'from': self.account.address,
            'nonce': nonce + 1,
            'gas': 10000000,
            'gasPrice': int(self.web3.eth.gas_price)
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


# if __name__ == "__main__":
#     pair_address = Web3.to_checksum_address('0xE6C694f8B9EE84353a10de59c9b4cDEFa0F5b4Ad') # replace with actual 
#     amount_in = 10 ** 5 # example amount
#     token_in_is0 = True
#     dex = AerodromeV3Dex(pair_address)
#     dex.get_price()
#     dex.swap(amount_in, token_in_is0, amount_out_min=0)
