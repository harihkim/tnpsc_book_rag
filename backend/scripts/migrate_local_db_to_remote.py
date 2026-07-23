import argparse
import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Ensure backend/src is in sys.path regardless of current working directory
_backend_src = Path(__file__).resolve().parents[1] / "src"
if _backend_src.exists() and str(_backend_src) not in sys.path:
    sys.path.insert(0, str(_backend_src))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from tnpsc_book_rag.config import Settings  # noqa: E402


def _resolve_settings() -> Settings:
    candidates = [
        Path.cwd() / ".env",
        Path.cwd() / "backend" / ".env",
        Path(__file__).resolve().parents[1] / ".env",
        Path(__file__).resolve().parents[2] / ".env",
    ]
    env_file = next((p for p in candidates if p.is_file()), None)
    if env_file:
        print(f"Loading configuration from environment file '{env_file}'...")
        return Settings(_env_file=env_file)
    return Settings()


def _resolve_dump_file(custom_path: str | None) -> Path:
    if custom_path:
        p = Path(custom_path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Specified dump file not found at '{p}'")
        return p

    search_locations = [
        Path.cwd() / "local_tnpsc_data.sql",
        Path.cwd() / "backend" / "local_tnpsc_data.sql",
        Path(__file__).resolve().parents[1] / "local_tnpsc_data.sql",
        Path(__file__).resolve().parents[2] / "local_tnpsc_data.sql",
    ]
    dump_file = next((p for p in search_locations if p.is_file()), None)
    if not dump_file:
        raise FileNotFoundError(
            "Could not locate 'local_tnpsc_data.sql'. Provide explicit path via --dump-file."
        )
    return dump_file


def _resolve_database_url(cli_value: str | None, settings: Settings) -> str:
    if cli_value:
        return cli_value
    if settings.database_url is None:
        raise ValueError(
            "No database URL provided via --db-url or TNPSC_DATABASE_URL environment variable."
        )
    return str(settings.database_url.get_secret_value())


async def _check_connectivity(database_url: str) -> None:
    print("Verifying target database connectivity...")
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            await conn.scalar(text("SELECT 1;"))
        print("Target database is reachable.")
    except Exception as exc:
        print(f"Error: Cannot connect to target database: {exc}")
        sys.exit(1)
    finally:
        await engine.dispose()


async def _ensure_pgvector(database_url: str) -> None:
    print("Connecting to database to verify pgvector extension...")
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        print("Extension 'vector' confirmed in target database.")
    finally:
        await engine.dispose()


def _restore_sql_dump_psql(database_url: str, dump_file: Path) -> bool:
    psql_bin = shutil.which("psql")
    if not psql_bin:
        print("'psql' CLI not found on PATH. Will use Python SQL execution fallback.")
        return False

    # Convert async driver URLs (postgresql+asyncpg:// or postgresql+psycopg://) to libpq URL
    libpq_url = database_url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )

    print(f"Restoring SQL dump '{dump_file.name}' using psql...")
    command_environment = os.environ.copy()
    command_environment["PGDATABASE"] = libpq_url
    cmd = [psql_bin, "-1", "--set", "ON_ERROR_STOP=1", "-f", str(dump_file)]
    try:
        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            check=False,
            env=command_environment,
        )
        if result.returncode == 0:
            print("psql restore completed successfully.")
            return True
        else:
            print(f"psql returned exit code {result.returncode}. Output:\n{result.stderr[-1000:]}")
            return False
    except Exception as exc:
        print(f"Failed to run psql command: {exc}")
        return False


async def _restore_sql_dump_python(database_url: str, dump_file: Path) -> None:
    print(f"Reading SQL dump file '{dump_file.name}'...")
    content = dump_file.read_text(encoding="utf-8")

    if "COPY " in content and " FROM stdin;" in content:
        raise RuntimeError(
            "Dump contains COPY data blocks which cannot be safely split on ';'. "
            "Install the PostgreSQL 'psql' CLI to restore this file correctly."
        )

    # Split non-empty SQL commands (strip comments/empty lines where feasible)
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("--") and not stripped.startswith("\\"):
            lines.append(line)

    full_sql = "\n".join(lines)
    statements = [stmt.strip() for stmt in full_sql.split(";") if stmt.strip()]

    print(f"Executing {len(statements)} SQL statements on target database...")
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            executed = 0
            for stmt in statements:
                await conn.execute(text(stmt))
                executed += 1
        print(f"Executed {executed} statements successfully.")
    finally:
        await engine.dispose()


def _run_alembic_upgrade(backend_root: Path) -> None:
    alembic_ini_path = backend_root / "alembic.ini"
    if not alembic_ini_path.is_file():
        print(
            f"Warning: alembic.ini not found at '{alembic_ini_path}'. Skipping Alembic migration."
        )
        return

    print("Running Alembic migrations (upgrade head)...")
    cfg = Config(str(alembic_ini_path))
    command.upgrade(cfg, "head")
    print("Alembic migrations applied up to head.")


async def _audit_database(database_url: str) -> dict[str, int]:
    print("\nAuditing restored database records...")
    engine = create_async_engine(database_url, isolation_level="AUTOCOMMIT")
    tables = [
        "books",
        "book_documents",
        "ingestion_runs",
        "pages",
        "content_units",
        "chunks",
        "chunk_embeddings",
        "assets",
    ]
    counts: dict[str, int] = {}
    alembic_rev: str = "NOT SET"
    try:
        async with engine.connect() as conn:
            for table in tables:
                try:
                    res = await conn.scalar(text(f"SELECT COUNT(*) FROM {table};"))  # noqa: S608
                    counts[table] = int(res) if res is not None else 0
                except Exception as exc:
                    print(f"Could not count records for table '{table}': {exc}")
                    counts[table] = -1
            try:
                rev = await conn.scalar(text("SELECT version_num FROM alembic_version LIMIT 1;"))
                alembic_rev = str(rev) if rev else "NOT SET"
            except Exception:
                alembic_rev = "N/A"
    finally:
        await engine.dispose()

    print("=" * 40)
    print("DATABASE AUDIT REPORT")
    print("=" * 40)
    for table, count in counts.items():
        print(f"  - {table:20s}: {count if count >= 0 else 'N/A'}")
    print(f"  - {'alembic_version':20s}: {alembic_rev}")
    print("=" * 40)
    return counts


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate local PostgreSQL database dump to target remote database."
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="Target database URL (overrides TNPSC_DATABASE_URL).",
    )
    parser.add_argument(
        "--dump-file",
        type=str,
        default=None,
        help="Path to SQL dump file (defaults to local_tnpsc_data.sql).",
    )
    parser.add_argument(
        "--skip-restore",
        action="store_true",
        help="Skip restoring SQL dump and only run migrations & audit.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Proceed even if the target database already contains data.",
    )

    args = parser.parse_args()

    try:
        target_url = _resolve_database_url(args.db_url, _resolve_settings())
    except ValueError as error:
        print(f"Error: {error}")
        sys.exit(1)

    print("Target Database URL configured.")

    backend_root = Path(__file__).resolve().parents[1]

    # Pre-flight connectivity check
    await _check_connectivity(target_url)

    # Ensure pgvector extension
    await _ensure_pgvector(target_url)

    if not args.skip_restore:
        if not args.force:
            pre_counts = await _audit_database(target_url)
            if any(v > 0 for v in pre_counts.values()):
                print("Error: Target database already contains data. Use --force to overwrite.")
                sys.exit(1)
        dump_path = _resolve_dump_file(args.dump_file)
        mb_size = dump_path.stat().st_size / (1024 * 1024)
        print(f"Resolved local SQL dump file: '{dump_path}' ({mb_size:.2f} MB)")

        success = _restore_sql_dump_psql(target_url, dump_path)
        if not success:
            await _restore_sql_dump_python(target_url, dump_path)

    # Run Alembic upgrade head
    os.environ["TNPSC_DATABASE_URL"] = target_url
    _run_alembic_upgrade(backend_root)

    # Audit database records
    await _audit_database(target_url)
    print("\nDatabase migration script completed successfully.")


if __name__ == "__main__":
    asyncio.run(main())
