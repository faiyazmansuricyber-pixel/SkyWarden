from __future__ import annotations

from target_app.db import DEFAULT_DB_PATH
from scripts.seed import seed_database


def main() -> None:
    seed_database(DEFAULT_DB_PATH, reset_existing=True)
    print(f"Reset and reseeded synthetic SkyVoyage data in {DEFAULT_DB_PATH}.")


if __name__ == "__main__":
    main()
