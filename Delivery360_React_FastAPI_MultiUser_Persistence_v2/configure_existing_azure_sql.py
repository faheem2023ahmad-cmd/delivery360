"""Configure the existing database using the signed-in Azure CLI administrator.

Preserves table data; adds read-only name aliases and the app identity's roles.
Run locally, not as the application startup command.
"""
import os
from pathlib import Path

import mssql_python
from azure.identity import AzureCliCredential
from delivery360_core import DATASETS

os.environ['PATH'] = str(Path('C:/Program Files/Microsoft SDKs/Azure/CLI2/wbin')) + os.pathsep + os.environ['PATH']
aliases = {
    'leave_records': 'leave_records-TBD',
    'onboarding_steps': 'onboarding_steps-TBD',
    'role_requirements': 'role_requirements-TBD',
    'sow_named_resources': 'sow_named_resources_TBD',
}

def main():
    connection = mssql_python.connect(
        'Server=tcp:delivery360server.database.windows.net,1433;'
        'Database=delivery360_test;Encrypt=yes;TrustServerCertificate=no;',
        token_provider=AzureCliCredential(), timeout=30,
    )
    try:
        cursor = connection.cursor()
        for target, source in aliases.items():
            cursor.execute('SELECT OBJECT_ID(?)', (f'dbo.{target}',))
            if cursor.fetchone()[0] is None:
                columns = ', '.join(f'[{column}]' for column in DATASETS[target][0])
                cursor.execute(f'CREATE VIEW dbo.[{target}] AS SELECT {columns} FROM dbo.[{source}]')
                print(f'Created view {target} over {source}')
        cursor.execute("IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name=N'delivery360') CREATE USER [delivery360] FROM EXTERNAL PROVIDER")
        for role in ('db_datareader', 'db_datawriter'):
            cursor.execute(
                "SELECT 1 FROM sys.database_role_members m "
                "JOIN sys.database_principals r ON r.principal_id=m.role_principal_id "
                "JOIN sys.database_principals u ON u.principal_id=m.member_principal_id "
                "WHERE r.name=? AND u.name=?", (role, 'delivery360'))
            if cursor.fetchone() is None:
                cursor.execute(f'ALTER ROLE [{role}] ADD MEMBER [delivery360]')
        connection.commit()
        for table in (*DATASETS, 'users', 'conversations', 'messages'):
            cursor.execute(f'SELECT COUNT_BIG(*) FROM dbo.[{table}]')
            print(f'{table}: {cursor.fetchone()[0]} rows')
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

if __name__ == '__main__':
    main()
