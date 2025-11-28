import os
import glob
import time
import mysql.connector
from mysql.connector import errorcode

DB_HOST = os.getenv("DB_HOST", "srv-captain--carbookdb-db")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "")
DB_NAME = os.getenv("DB_NAME", "carhistory")

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations")
LOCK_NAME = f"{DB_NAME}_migrate_lock"


# --- Helper to drain unread result sets to avoid MariaDB errors ---
def _drain(cur):
    """Consume all unread results to avoid 'Unread result found' errors."""
    try:
        # Drain current result
        if cur.with_rows:
            try:
                cur.fetchall()
            except:
                pass

        # Drain any additional result sets (multi-statement)
        while True:
            try:
                more = cur.nextset()
            except:
                break
            if not more:
                break
            if cur.with_rows:
                try:
                    cur.fetchall()
                except:
                    pass
    except:
        pass


def _connect(db=None):
    return mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        database=db,
        autocommit=False,
    )


def _ensure_database():
    conn = _connect(db=None)
    cur = conn.cursor()
    cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_520_ci"
    )
    _drain(cur)
    conn.commit()
    cur.close()
    conn.close()


def _ensure_schema_migrations(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INT PRIMARY KEY,
            applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    _drain(cur)


def _get_applied_versions(cur):
    cur.execute("SELECT version FROM schema_migrations ORDER BY version")
    rows = cur.fetchall()
    _drain(cur)
    return {row[0] for row in rows}


def _apply_migration(cur, version, sql_text):
    statements = [s.strip() for s in sql_text.split(";") if s.strip()]

    for stmt in statements:
        cur.execute(stmt)
        _drain(cur)

    cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
    _drain(cur)


def _acquire_lock(cur, timeout_seconds=30):
    cur.execute("SELECT GET_LOCK(%s, %s)", (LOCK_NAME, timeout_seconds))
    row = cur.fetchone()
    _drain(cur)
    return bool(row and row[0] == 1)


def _release_lock(cur):
    cur.execute("SELECT RELEASE_LOCK(%s)", (LOCK_NAME,))
    _drain(cur)


def is_database_initialized():
    try:
        conn = _connect(db=DB_NAME)
    except mysql.connector.Error:
        return False

    try:
        cur = conn.cursor()

        cur.execute("SHOW TABLES LIKE 'users'")
        exists = cur.fetchone()
        _drain(cur)
        if exists is None:
            cur.close()
            conn.close()
            return False

        cur.execute("SELECT COUNT(*) FROM users")
        (count,) = cur.fetchone()
        _drain(cur)

        cur.close()
        conn.close()
        return count > 0

    except:
        try:
            cur.close()
        except:
            pass
        conn.close()
        return False


def run_migrations_once():
    _ensure_database()
    conn = _connect(db=DB_NAME)
    cur = conn.cursor()

    if not _acquire_lock(cur, timeout_seconds=30):
        cur.close()
        conn.close()
        time.sleep(1.0)
        return

    try:
        _ensure_schema_migrations(cur)
        conn.commit()

        applied = _get_applied_versions(cur)

        files = sorted(
            glob.glob(os.path.join(MIGRATIONS_DIR, "[0-9][0-9][0-9]_*.sql"))
        )

        for path in files:
            fname = os.path.basename(path)
            version_str = fname.split("_", 1)[0]

            try:
                version = int(version_str)
            except ValueError:
                continue

            if version in applied:
                continue

            with open(path, "r", encoding="utf-8") as f:
                sql_text = f.read()

            try:
                _apply_migration(cur, version, sql_text)
                conn.commit()
                print(f"Applied migration {version}: {fname}")
            except Exception as e:
                conn.rollback()
                raise RuntimeError(
                    f"Failed applying migration {fname}: {e}"
                ) from e

    finally:
        _release_lock(cur)
        conn.commit()
        cur.close()
        conn.close()
