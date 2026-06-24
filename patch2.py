import re

# Fix execution.py
with open('agents/execution.py', 'r', encoding='utf-8') as f:
    code = f.read()

code = code.replace('self.live_engine.paper_record().get("promotion", {}).get("passed", False)', 'self.live_engine.paper_record.get("promotion", {}).get("passed", False)')

with open('agents/execution.py', 'w', encoding='utf-8') as f:
    f.write(code)

# Fix analysis.py
with open('backend/routers/analysis.py', 'r', encoding='utf-8') as f:
    code = f.read()

if 'from sqlalchemy import text' not in code:
    code = code.replace('from sqlalchemy.ext.asyncio import AsyncSession', 'from sqlalchemy.ext.asyncio import AsyncSession\nfrom sqlalchemy import text')
    with open('backend/routers/analysis.py', 'w', encoding='utf-8') as f:
        f.write(code)

# Fix binance.py
with open('live_trading/exchange/binance.py', 'r', encoding='utf-8') as f:
    code = f.read()

stub_code = """
import typing
if typing.TYPE_CHECKING:
    import ccxt.async_support as ccxt
    import ccxt.pro as ccxt_pro
    HAS_CCXT = True
else:
    try:
        import ccxt.async_support as ccxt
        import ccxt.pro as ccxt_pro

        HAS_CCXT = True
    except ImportError:  # pragma: no cover
        HAS_CCXT = False
        import sys
        class _Dummy:
            pass
        ccxt = _Dummy()
        ccxt.AuthenticationError = Exception
        ccxt.NetworkError = Exception
        ccxt.InsufficientFunds = Exception
        ccxt.InvalidOrder = Exception
"""

target = """try:
    import ccxt.async_support as ccxt
    import ccxt.pro as ccxt_pro

    HAS_CCXT = True
except ImportError:  # pragma: no cover
    HAS_CCXT = False
    ccxt = None"""

if target in code:
    code = code.replace(target, stub_code.strip())
else:
    print("Could not find ccxt import block in binance.py")

with open('live_trading/exchange/binance.py', 'w', encoding='utf-8') as f:
    f.write(code)
print("Done patching.")
