import asyncio

from backend.routers.live import _get_engine


async def main():
    e = _get_engine()
    print("Engine:", e)
    res = await e.start()
    print("Result:", res)

if __name__ == "__main__":
    asyncio.run(main())
