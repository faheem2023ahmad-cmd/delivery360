"""Azure SQL connection and idempotent schema setup for Delivery 360."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator


CONNECTION_STRING_ENV = 'DELIVERY360_AZURE_SQL_CONNECTION_STRING'


def azure_sql_enabled() -> bool:
    return bool(os.getenv(CONNECTION_STRING_ENV, '').strip())


class Record(dict):
    """Dictionary row that also supports SQLite-style numeric indexing."""
    def __init__(self, columns: list[str], values: Any):
        super().__init__(zip(columns, values))
        self._columns = columns

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            key = self._columns[key]
        return super().__getitem__(key)


class CursorAdapter:
    def __init__(self, cursor: Any):
        self._cursor = cursor
        self._columns = [column[0] for column in (cursor.description or [])]
        self.description = cursor.description

    def _record(self, row: Any) -> Record | None:
        return Record(self._columns, row) if row is not None else None

    def fetchone(self) -> Record | None:
        return self._record(self._cursor.fetchone())

    def fetchall(self) -> list[Record]:
        return [self._record(row) for row in self._cursor.fetchall()]

    def fetchmany(self, size: int) -> list[Record]:
        return [self._record(row) for row in self._cursor.fetchmany(size)]


class AzureSQLConnection:
    """Small DB-API adapter for the SQLite-like execute call sites in the app."""
    def __init__(self, connection: Any):
        self._connection = connection

    def execute(self, statement: str, parameters: Any = ()) -> CursorAdapter:
        cursor = self._connection.cursor()
        cursor.execute(statement, parameters)
        return CursorAdapter(cursor)

    def executemany(self, statement: str, parameter_sets: Any) -> CursorAdapter:
        cursor = self._connection.cursor()
        cursor.executemany(statement, parameter_sets)
        return CursorAdapter(cursor)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()


@contextmanager
def connect() -> Iterator[AzureSQLConnection]:
    connection_string = os.getenv(CONNECTION_STRING_ENV, '').strip()
    if not connection_string:
        raise RuntimeError(f'{CONNECTION_STRING_ENV} is required for Azure SQL mode')

    try:
        import mssql_python
    except ImportError as exc:
        raise RuntimeError('Install mssql-python to connect to Azure SQL') from exc

    raw = mssql_python.connect(connection_string)
    try:
        yield AzureSQLConnection(raw)
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def _execute_all(db: AzureSQLConnection, statements: list[str]) -> None:
    for statement in statements:
        db.execute(statement)


def chat_schema_statements() -> list[str]:
    return [
        "IF OBJECT_ID(N'dbo.users', N'U') IS NULL CREATE TABLE dbo.users (username NVARCHAR(100) NOT NULL PRIMARY KEY, password_hash VARCHAR(128) NOT NULL, created_at NVARCHAR(40) NOT NULL)",
        "IF OBJECT_ID(N'dbo.sessions', N'U') IS NULL CREATE TABLE dbo.sessions (token_hash CHAR(64) NOT NULL PRIMARY KEY, username NVARCHAR(100) NOT NULL, csrf_hash CHAR(64) NOT NULL, expires_at NVARCHAR(40) NOT NULL, CONSTRAINT FK_sessions_users FOREIGN KEY (username) REFERENCES dbo.users(username))",
        "IF OBJECT_ID(N'dbo.conversations', N'U') IS NULL CREATE TABLE dbo.conversations (id CHAR(36) NOT NULL PRIMARY KEY, owner NVARCHAR(100) NOT NULL, title NVARCHAR(120) NOT NULL, workspace NVARCHAR(40) NOT NULL, created_at NVARCHAR(40) NOT NULL, updated_at NVARCHAR(40) NOT NULL, agent_history NVARCHAR(MAX) NOT NULL CONSTRAINT DF_conversations_agent_history DEFAULT N'[]', turns INT NOT NULL CONSTRAINT DF_conversations_turns DEFAULT 0, summary NVARCHAR(MAX) NOT NULL CONSTRAINT DF_conversations_summary DEFAULT N'', refs_json NVARCHAR(MAX) NOT NULL CONSTRAINT DF_conversations_refs_json DEFAULT N'{}', CONSTRAINT FK_conversations_users FOREIGN KEY (owner) REFERENCES dbo.users(username))",
        "IF OBJECT_ID(N'dbo.messages', N'U') IS NULL CREATE TABLE dbo.messages (id CHAR(36) NOT NULL PRIMARY KEY, conversation_id CHAR(36) NOT NULL, role NVARCHAR(20) NOT NULL, content NVARCHAR(MAX) NOT NULL, created_at NVARCHAR(40) NOT NULL, CONSTRAINT FK_messages_conversations FOREIGN KEY (conversation_id) REFERENCES dbo.conversations(id) ON DELETE CASCADE)",
        "IF OBJECT_ID(N'dbo.tool_executions', N'U') IS NULL CREATE TABLE dbo.tool_executions (id CHAR(36) NOT NULL PRIMARY KEY, conversation_id CHAR(36) NOT NULL, message_id CHAR(36) NOT NULL, tool_name NVARCHAR(200) NOT NULL, status NVARCHAR(20) NOT NULL, created_at NVARCHAR(40) NOT NULL, CONSTRAINT FK_tool_executions_conversations FOREIGN KEY (conversation_id) REFERENCES dbo.conversations(id) ON DELETE CASCADE)",
        "IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'idx_owner_updated' AND object_id=OBJECT_ID(N'dbo.conversations')) CREATE INDEX idx_owner_updated ON dbo.conversations(owner, updated_at)",
        "IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'idx_messages_conversation' AND object_id=OBJECT_ID(N'dbo.messages')) CREATE INDEX idx_messages_conversation ON dbo.messages(conversation_id, created_at, id)",
        "IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name=N'idx_sessions_user' AND object_id=OBJECT_ID(N'dbo.sessions')) CREATE INDEX idx_sessions_user ON dbo.sessions(username)",
    ]


def ensure_chat_schema(db: AzureSQLConnection) -> None:
    _execute_all(db, chat_schema_statements())


def business_schema_statements() -> list[str]:
    # Import lazily to avoid a module cycle: the schema definitions live with the domain data.
    from delivery360_core import DATASETS, FOREIGN_KEYS, NUMERIC_FIELDS

    statements = []
    for table, fixture in DATASETS.items():
        columns = list(fixture[0])
        primary_key = columns[0]
        fields = []
        for column in columns:
            if NUMERIC_FIELDS.get(column) == 'REAL':
                sql_type = 'FLOAT'
            elif NUMERIC_FIELDS.get(column) == 'INTEGER':
                sql_type = 'INT'
            elif column == primary_key or column in FOREIGN_KEYS.get(table, {}):
                sql_type = 'NVARCHAR(100)'
            else:
                sql_type = 'NVARCHAR(4000)'
            nullability = ' NOT NULL' if column == primary_key else ' NULL'
            fields.append(f'[{column}] {sql_type}{nullability}')

        fields.append(f'CONSTRAINT [PK_{table}] PRIMARY KEY ([{primary_key}])')
        for column, (target, target_key) in FOREIGN_KEYS.get(table, {}).items():
            fields.append(
                f'CONSTRAINT [FK_{table}_{column}] FOREIGN KEY ([{column}]) '
                f'REFERENCES dbo.[{target}] ([{target_key}])'
            )
        column_sql = ', '.join(fields)
        statements.append(
            f"IF OBJECT_ID(N'dbo.{table}', N'U') IS NULL "
            f'CREATE TABLE dbo.[{table}] ({column_sql})'
        )

    return statements


def ensure_business_schema(db: AzureSQLConnection) -> None:
    _execute_all(db, business_schema_statements())
