import re

with open('scripts/run_live.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Add missing imports
if 'from agents.market_analyst import MarketAnalystAgent' not in code:
    imports_to_add = """from agents.market_analyst import MarketAnalystAgent
from agents.quant import QuantAgent
from agents.risk import RiskAgent
from agents.execution import ExecutionAgent
from agents.journal import JournalAgent
from agents.reflection import ReflectionAgent
from agents.memory import MemoryAgent"""
    code = code.replace(
        'from agents.registry import AgentRegistry',
        'from agents.registry import AgentRegistry\n' + imports_to_add
    )

# 2. Fix stream_analysis call
code = code.replace(
    'pipeline.stream_analysis(request=latest_candle, context_params=mem_params)',
    'pipeline.stream_analysis(symbol=target_symbol, request="Live analysis run")'
)

with open('scripts/run_live.py', 'w', encoding='utf-8') as f:
    f.write(code)
print("run_live.py patched successfully")
