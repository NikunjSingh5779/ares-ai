import asyncio
from database.connection import async_session_factory
from sqlalchemy import text

async def seed():
    async with async_session_factory() as s:
        # Create user
        user_res = await s.execute(text("""
            INSERT INTO users (email, password_hash, display_name)
            VALUES ('system@ares.ai', 'hash', 'System')
            ON CONFLICT (email) DO NOTHING
            RETURNING id;
        """))
        user_id = user_res.scalar()
        if not user_id:
            user_id = (await s.execute(text("SELECT id FROM users WHERE email='system@ares.ai'"))).scalar()

        # Create account
        acc_res = await s.execute(text("""
            INSERT INTO accounts (user_id, exchange, account_name)
            VALUES (:user_id, 'paper', 'Paper Trading')
            ON CONFLICT (user_id, exchange, account_name) DO NOTHING
            RETURNING id;
        """), {'user_id': user_id})
        acc_id = acc_res.scalar()
        if not acc_id:
            acc_id = (await s.execute(text("SELECT id FROM accounts WHERE user_id=:user_id AND exchange='paper'"), {'user_id': user_id})).scalar()

        # Create portfolio (there is no unique constraint so check first)
        port_id = (await s.execute(text("SELECT id FROM portfolio WHERE account_id=:account_id"), {'account_id': acc_id})).scalar()
        if not port_id:
            port_res = await s.execute(text("""
                INSERT INTO portfolio (account_id, total_value, cash_balance)
                VALUES (:account_id, 100000, 100000)
                RETURNING id;
            """), {'account_id': acc_id})
            port_id = port_res.scalar()

        await s.commit()
        print(f'User: {user_id}, Account: {acc_id}, Portfolio: {port_id}')

asyncio.run(seed())
