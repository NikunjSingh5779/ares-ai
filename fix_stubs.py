stubs = ['live_trading/exchange/ibkr.py', 'live_trading/exchange/zerodha.py']
for stub in stubs:
    with open(stub, 'r') as f:
        c = f.read()
    if 'async def cancel_all_orders' not in c:
        c += """
    async def cancel_all_orders(self, symbol: str) -> bool:
        raise NotImplementedError("cancel_all_orders not yet implemented")
"""
        with open(stub, 'w') as f:
            f.write(c)
