import argparse
from pathlib import Path

from app.database import DATABASE_PATH, engine, initialize_database, verify_database_schema
from app.database_backup import create_sqlite_backup


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Back up and explicitly apply the current additive SQLite schema updates."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        required=True,
        help="Confirm that this command may modify the selected database.",
    )
    parser.add_argument(
        "--backup",
        type=Path,
        required=True,
        help="New backup file path created before applying schema updates.",
    )
    arguments = parser.parse_args()

    if not DATABASE_PATH.is_file():
        parser.error(f"Database file does not exist: {DATABASE_PATH}")

    backup_path = create_sqlite_backup(DATABASE_PATH, arguments.backup)
    print(f"Pre-migration backup created: {backup_path}")
    initialize_database(engine)
    verify_database_schema(engine)
    print("Schema checks completed successfully.")


if __name__ == "__main__":
    main()
