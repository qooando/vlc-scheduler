import asyncio
from src import build, scheduler

async def main():
    await build.main()
    await scheduler.main()


if __name__ == "__main__":
    asyncio.run(main())
