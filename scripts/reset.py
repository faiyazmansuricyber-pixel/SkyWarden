from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from target_app.db import DEFAULT_DB_PATH
from scripts.seed import seed_database


def reset_database(
    db_path: Path = DEFAULT_DB_PATH,
    environ: Mapping[str, str] | None = None,
) -> None:
    seed_database(db_path, environ=environ, reset_existing=True)


def main() -> None:
    reset_database()
    print(f"Reset and reseeded synthetic SkyVoyage data in {DEFAULT_DB_PATH}.")


if __name__ == "__main__":
    main()
