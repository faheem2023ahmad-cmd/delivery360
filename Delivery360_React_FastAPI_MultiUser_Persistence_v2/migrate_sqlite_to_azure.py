"""One-time migration of the two Delivery 360 SQLite databases to Azure SQL."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from azure_sql import (
    CONNECTION_STRING_ENV,
    connect,
    ensure_business_schema,
    ensure_chat_schema,
)
from delivery360_core import DATASETS

ROOT = Path(__file__).resolve().parent
STATE = Path(os.getenv('DELIVERY360_STATE_DIR', str(ROOT / 'state')))
BUSINESS_DB = Path(os.getenv('DELIVERY360_DB_PATH', str(STATE / 'delivery360_poc.db')))
CHAT_DB = Path(os.getenv('DELIVERY360_CHAT_DB_PATH', str(STATE / 'delivery360_chats.db')))
CHAT_TABLES = ('users', 'sessions', 'conversations', 'messages', 'tool_executions')


def sqlite_rows(path: Path, table: str) -> tuple[list[str], list[tuple]]:
    if not path.is_file():
        raise FileNotFoundError(f'Source SQLite database not found: {path}')
    with sqlite3.connect(f'file:{path.resolve().as_posix()}?mode=ro', uri=True) as source:
        source.row_factory = sqlite3.Row
        columns = [item[1] for item in source.execute(f'PRAGMA table_info("{table}")')]
        if not columns:
            raise ValueError(f'{table} was not found in {path.name}')
        rows = [tuple(row[column] for column in columns) for row in source.execute(f'SELECT * FROM "{table}"')]
        return columns, rows


def migrate() -> dict[str, int]:
    business_tables = tuple(DATASETS)
    tables = business_tables + CHAT_TABLES
    source_files = {table: BUSINESS_DB for table in business_tables}
    source_files.update({table: CHAT_DB for table in CHAT_TABLES})
    source_data = {table: sqlite_rows(source_files[table], table) for table in tables}

    with connect() as db:
        ensure_business_schema(db)
        ensure_chat_schema(db)

        existing = {
            table: db.execute(f'SELECT COUNT_BIG(*) FROM dbo.[{table}]').fetchone()[0]
            for table in tables
        }
        populated = {table: count for table, count in existing.items() if count}
        if populated:
            if len(populated) != len(tables):
                raise RuntimeError(
                    'Migration stopped without inserting rows because only some destination tables contain data: '
                    + ', '.join(f'{table}={count}' for table, count in populated.items())
                )
            for table in tables:
                columns, expected_rows = source_data[table]
                if existing[table] != len(expected_rows):
                    raise RuntimeError(
                        f'{table}: source has {len(expected_rows)} rows but destination has {existing[table]}'
                    )
                key = columns[0]
                selected_columns = ', '.join(f'[{column}]' for column in columns)
                actual_rows = db.execute(
                    f'SELECT {selected_columns} FROM dbo.[{table}] ORDER BY [{key}]'
                ).fetchall()
                expected_rows = sorted(expected_rows, key=lambda row: row[0])
                actual_values = [tuple(row[column] for column in columns) for row in actual_rows]
                if actual_values != expected_rows:
                    raise RuntimeError(f'{table}: destination rows differ from the SQLite source')
            return {table: len(source_data[table][1]) for table in tables}

        counts = {}
        for table in tables:
            columns, rows = source_data[table]
            names = ', '.join(f'[{column}]' for column in columns)
            placeholders = ', '.join('?' for _ in columns)
            db.executemany(
                f'INSERT INTO dbo.[{table}] ({names}) VALUES ({placeholders})',
                rows,
            )
            counts[table] = len(rows)

    return counts


if __name__ == '__main__':
    if not os.getenv(CONNECTION_STRING_ENV):
        raise SystemExit(f'Set {CONNECTION_STRING_ENV} to the Azure SQL connection string before migrating.')
    for table, count in migrate().items():
        print(f'{table}: {count} rows migrated or verified')
