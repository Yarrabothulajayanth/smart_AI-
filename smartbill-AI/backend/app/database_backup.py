import argparse
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from uuid import uuid4

from app.database import DATABASE_PATH


def _check_database(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {path}")
    connection = sqlite3.connect(str(path), timeout=30)
    try:
        result = connection.execute("PRAGMA quick_check").fetchone()
    finally:
        connection.close()
    if result != ("ok",):
        raise ValueError(f"SQLite integrity check failed for {path}.")


def create_sqlite_backup(source: Path, destination: Path) -> Path:
    source_path = source.expanduser().resolve()
    destination_path = destination.expanduser().resolve()
    if source_path == destination_path:
        raise ValueError("The backup destination must differ from the source.")
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {source_path}")
    if destination_path.exists():
        raise FileExistsError(f"Backup already exists: {destination_path}")

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination_path.with_name(
        f".{destination_path.name}.{uuid4().hex}.tmp"
    )
    try:
        with (
            closing(sqlite3.connect(str(source_path), timeout=30)) as source_connection,
            closing(sqlite3.connect(str(temporary_path), timeout=30)) as backup_connection,
        ):
            source_connection.backup(backup_connection)
            backup_connection.commit()
        _check_database(temporary_path)
        if destination_path.exists():
            raise FileExistsError(f"Backup already exists: {destination_path}")
        temporary_path.rename(destination_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return destination_path


def restore_sqlite_backup(
    backup: Path,
    target: Path,
    *,
    confirm_overwrite: bool = False,
) -> Path:
    backup_path = backup.expanduser().resolve()
    target_path = target.expanduser().resolve()
    if backup_path == target_path:
        raise ValueError("The backup and restore target must be different files.")
    _check_database(backup_path)

    if target_path.exists() and not confirm_overwrite:
        raise PermissionError(
            "The target already exists; pass confirm_overwrite=True only after "
            "reviewing the recovery plan."
        )
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if target_path.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safety_backup = target_path.with_name(
            f"{target_path.stem}.before-restore-{timestamp}{target_path.suffix}"
        )
        create_sqlite_backup(target_path, safety_backup)

    source_connection = sqlite3.connect(str(backup_path), timeout=30)
    target_connection = sqlite3.connect(str(target_path), timeout=30)
    try:
        source_connection.backup(target_connection)
        target_connection.commit()
    finally:
        target_connection.close()
        source_connection.close()

    _check_database(target_path)
    return target_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create or restore a consistent SQLite backup."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    backup_command = commands.add_parser("backup", help="Create a SQLite backup.")
    backup_command.add_argument(
        "--source", type=Path, default=DATABASE_PATH, help="Source database file."
    )
    backup_command.add_argument(
        "--destination", type=Path, required=True, help="New backup file path."
    )

    restore_command = commands.add_parser(
        "restore", help="Restore a backup while the application is stopped."
    )
    restore_command.add_argument(
        "--backup", type=Path, required=True, help="Verified backup file."
    )
    restore_command.add_argument(
        "--target", type=Path, default=DATABASE_PATH, help="Database to restore."
    )
    restore_command.add_argument(
        "--confirm-overwrite",
        action="store_true",
        help="Required to replace an existing target; a safety backup is created.",
    )

    arguments = parser.parse_args()
    if arguments.command == "backup":
        path = create_sqlite_backup(arguments.source, arguments.destination)
        print(f"Verified backup created: {path}")
    else:
        path = restore_sqlite_backup(
            arguments.backup,
            arguments.target,
            confirm_overwrite=arguments.confirm_overwrite,
        )
        print(f"Verified database restored: {path}")


if __name__ == "__main__":
    main()
