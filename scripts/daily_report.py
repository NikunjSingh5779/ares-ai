import asyncio
from sqlalchemy import text
from database.connection import async_session_factory
from datetime import datetime, timezone

async def generate_daily_report():
    print(f"--- ARES Live Run Daily Report for {datetime.now(timezone.utc).strftime('%Y-%m-%d')} ---")
    async with async_session_factory() as session:
        # 1. Evaluation cycles run
        result = await session.execute(text("""
            SELECT COUNT(*) FROM agent_logs 
            WHERE agent_name = 'supervisor' AND created_at >= NOW() - INTERVAL '1 day'
        """))
        cycles = result.scalar() or 0
        print(f"Evaluation cycles run in last 24h: {cycles}")

        # 2. Confidence ranges from market_analyst and quant
        result = await session.execute(text("""
            SELECT agent_name, 
                   MIN((output_data->>'confidence')::numeric), 
                   MAX((output_data->>'confidence')::numeric)
            FROM agent_logs
            WHERE agent_name IN ('market_analyst', 'quant') 
              AND created_at >= NOW() - INTERVAL '1 day'
              AND output_data->>'confidence' IS NOT NULL
            GROUP BY agent_name
        """))
        ranges = result.fetchall()
        print("Confidence ranges seen:")
        if not ranges:
            print("  None recorded with 'confidence' in output_data.")
        for row in ranges:
            print(f"  {row[0]}: {row[1]} to {row[2]}")
            
        # 3. Dual consensus cleared 80%?
        result = await session.execute(text("""
            SELECT MAX((output_data->>'consensus_score')::numeric)
            FROM agent_logs
            WHERE agent_name = 'supervisor' AND created_at >= NOW() - INTERVAL '1 day'
            AND output_data->>'consensus_score' IS NOT NULL
        """))
        max_consensus = result.scalar()
        if max_consensus is not None and max_consensus >= 80.0:
            print(f"Dual consensus cleared 80%: YES (Max seen: {max_consensus}%)")
        else:
            print(f"Dual consensus cleared 80%: NO (Max seen: {max_consensus if max_consensus is not None else 'N/A'}%)")

        # 4. Circuit breaker trips or rate limits
        result = await session.execute(text("""
            SELECT error_type, created_at FROM agent_logs 
            WHERE error_type IS NOT NULL AND created_at >= NOW() - INTERVAL '1 day'
            ORDER BY created_at ASC
        """))
        errors = result.fetchall()
        print(f"Circuit breaker trips / Rate limits / Errors: {len(errors)}")
        for e in errors:
            print(f"  [{e[1]}] {e[0]}")

if __name__ == "__main__":
    asyncio.run(generate_daily_report())
