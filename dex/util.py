def sqrt_ratio_x96_to_price(sqrt_ratio_x96: int, decimals0: int, decimals1: int) -> float:
    """
    Convert Uniswap V3 sqrtPriceX96 to price, considering token decimals.
    Args:
        sqrt_ratio_x96: int or str, the sqrtPriceX96 value
        decimals0: int, decimals of token0
        decimals1: int, decimals of token1
    Returns:
        float: price (token1 per token0)
    """
    sqrt = int(sqrt_ratio_x96)
    ratio = sqrt / 2 ** 96
    price = ratio * ratio
    price = price * 10 ** (decimals0 - decimals1)
    return price