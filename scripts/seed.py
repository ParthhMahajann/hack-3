"""Run this to seed the demo DB: python -m scripts.seed"""
import asyncio
from backend.database import init_db


async def main():
    await init_db()
    print("✅ Database initialized and demo data seeded.")
    print("\nDemo accounts:")
    print("  ASHA Worker : asha1@demo.in  / asha123")
    print("  Block Officer: officer@demo.in / officer123")

if __name__ == "__main__":
    asyncio.run(main())
