import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.database_backup import create_sqlite_backup, restore_sqlite_backup


class SQLiteBackupTest(unittest.TestCase):
    def test_backup_and_restore_preserve_a_consistent_database(self) -> None:
        with TemporaryDirectory(prefix="smartbill-backup-tests-") as directory:
            root = Path(directory)
            source = root / "shop.sqlite"
            backup = root / "backups" / "shop-backup.sqlite"
            connection = sqlite3.connect(source)
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(
                    "CREATE TABLE invoices (id INTEGER PRIMARY KEY, number TEXT)"
                )
                connection.execute(
                    "INSERT INTO invoices (number) VALUES ('SB-0001')"
                )
                connection.commit()
            finally:
                connection.close()

            create_sqlite_backup(source, backup)
            connection = sqlite3.connect(source)
            try:
                connection.execute(
                    "INSERT INTO invoices (number) VALUES ('SB-0002')"
                )
                connection.commit()
            finally:
                connection.close()

            restore_sqlite_backup(backup, source, confirm_overwrite=True)

            connection = sqlite3.connect(source)
            try:
                invoices = connection.execute(
                    "SELECT number FROM invoices ORDER BY id"
                ).fetchall()
            finally:
                connection.close()
            self.assertEqual(invoices, [("SB-0001",)])
            self.assertTrue(
                list(root.glob("shop.before-restore-*.sqlite"))
            )

    def test_overwrite_requires_explicit_confirmation(self) -> None:
        with TemporaryDirectory(prefix="smartbill-backup-confirmation-") as directory:
            root = Path(directory)
            source = root / "source.sqlite"
            backup = root / "backup.sqlite"
            connection = sqlite3.connect(source)
            try:
                connection.execute("CREATE TABLE records (id INTEGER)")
                connection.commit()
            finally:
                connection.close()

            create_sqlite_backup(source, backup)
            with self.assertRaises(PermissionError):
                restore_sqlite_backup(backup, source)

    def test_existing_backup_is_never_overwritten(self) -> None:
        with TemporaryDirectory(prefix="smartbill-backup-no-overwrite-") as directory:
            root = Path(directory)
            source = root / "source.sqlite"
            backup = root / "backup.sqlite"
            connection = sqlite3.connect(source)
            try:
                connection.execute("CREATE TABLE records (id INTEGER)")
                connection.commit()
            finally:
                connection.close()

            backup.write_bytes(b"keep this backup")
            with self.assertRaises(FileExistsError):
                create_sqlite_backup(source, backup)
            self.assertEqual(backup.read_bytes(), b"keep this backup")


if __name__ == "__main__":
    unittest.main()
