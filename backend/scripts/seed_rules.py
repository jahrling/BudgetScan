"""Load seed rules from YAML into the database. Idempotent."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from finance.db import async_session_factory, init_db
from finance.services.seed_rules import import_seed_rules


async def main() -> None:
    await init_db()
    yaml_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None

    async with async_session_factory() as session:
        print("Importing seed rules...")
        result = await import_seed_rules(session, yaml_path)
        print(f"  Created: {result.created}")
        print(f"  Updated: {result.updated}")
        print(f"  Skipped: {result.skipped}")
        if result.missing_categories:
            print(f"  Missing categories: {', '.join(result.missing_categories)}")
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
