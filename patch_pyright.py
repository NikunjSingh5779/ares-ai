import re

# Fix agents/execution.py
with open('agents/execution.py', 'r', encoding='utf-8') as f:
    code = f.read()

code = code.replace('self.live_engine.promotion_gate.is_passed()', 'self.live_engine.paper_record().get("promotion", {}).get("passed", False)')
with open('agents/execution.py', 'w', encoding='utf-8') as f:
    f.write(code)

# Fix backend/routers/analysis.py
with open('backend/routers/analysis.py', 'r', encoding='utf-8') as f:
    code = f.read()

if 'from sqlalchemy import text' not in code:
    code = code.replace('from sqlalchemy.ext.asyncio import async_sessionmaker', 'from sqlalchemy import text\nfrom sqlalchemy.ext.asyncio import async_sessionmaker')
    with open('backend/routers/analysis.py', 'w', encoding='utf-8') as f:
        f.write(code)

# Fix live_trading/engine.py
with open('live_trading/engine.py', 'r', encoding='utf-8') as f:
    code = f.read()

code = code.replace('self.mode_manager.set_mode(TradingMode.PAPER)', 'self.mode_manager.set_mode(TradingMode.HUMAN_APPROVAL)')
code = code.replace('Mode forced to PAPER.', 'Mode forced to HUMAN_APPROVAL.')
with open('live_trading/engine.py', 'w', encoding='utf-8') as f:
    f.write(code)

# Fix live_trading/exchange/binance.py
with open('live_trading/exchange/binance.py', 'r', encoding='utf-8') as f:
    code = f.read()

code = code.replace('import ccxt\n    import ccxt.pro as ccxt_pro', 'import ccxt.async_support as ccxt\n    import ccxt.pro as ccxt_pro')

# To fix "possibly unbound", we can just ignore or provide a stub
unbound_stub = '''except ImportError:  # pragma: no cover
    HAS_CCXT = False
    ccxt = None'''
code = code.replace('except ImportError:  # pragma: no cover\n    HAS_CCXT = False', unbound_stub)

with open('live_trading/exchange/binance.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("Patch applied")
