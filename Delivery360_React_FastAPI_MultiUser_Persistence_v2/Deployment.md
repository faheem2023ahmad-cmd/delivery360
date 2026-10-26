# Azure SQL deployment package

## Current demo settings (2026-10-26)

The owner requested public demo access. Application default access is set
to Allow and the `Delivery360-POC-client` IP allow rule was removed. Existing login
and HTTPS remain enabled. This supersedes the earlier IP-restricted POC notes.

Set `DELIVERY360_DISABLED_TABLES` to
`leave_records,onboarding_steps,role_requirements,sow_named_resources`.
These four datasets are deferred to phase 2: the Azure repository excludes them
from schema discovery and blocks reads and SQL queries. Dependent tools report
unavailable data instead of calculating results from empty placeholders. The
agent is instructed to explain these limitations. Original TBD tables and the
previously added views remain intact but are not queried by this configuration.
Remove names from this setting when their real data becomes available.

## Confirmed Azure resources (2026-10-25)

- Subscription: `65ed97e8-ca33-479b-b4f9-fe5536a7149f`
- Resource group: `Practice`
- Actual existing App Service: `delivery360` (not `deliver360`)
- Host: `https://delivery360-fchvgsg0gyafgbg9.westus3-01.azurewebsites.net`
- Existing database selected by the owner: `delivery360_test`
- Managed identity enabled; database reader/writer roles granted.
- Existing data preserved: 2 users, 8 conversations, 48 messages at inspection.
- Compatibility views map `leave_records`, `onboarding_steps`,
  `role_requirements`, and `sow_named_resources` to their existing TBD tables.
  `configure_existing_azure_sql.py` records the idempotent setup used.
- SQL firewall rules added for all 13 current App Service outbound IPs.
- On 2026-10-26, application access restricted to `172.190.100.99/32`
  with default deny. Deployment endpoint rules remain separate.
- Azure SQL connection configured for `delivery360_test` using managed identity;
  schema initialization disabled, secure cookies and HTTPS enabled.
- Startup set to `sh startup.sh`; server-side Python build enabled.
- Existing OpenAI API key retained; demo authentication enabled for the restricted POC.

Use this connection setting for these confirmed resources:

```text
Server=tcp:delivery360server.database.windows.net,1433;Database=delivery360_test;Authentication=ActiveDirectoryMSI;Encrypt=yes;TrustServerCertificate=no;
```

The examples below predate resource discovery. Substitute `delivery360` for
`deliver360` and `delivery360_test` for the database name in those examples.

## Package and deployment procedure

The prepared package is `delivery360-azure-sql.zip`. It includes `azure_sql.py`,
`startup.sh`, all runtime Python modules, requirements, CSV data, the migration
utility, and compiled React assets. It excludes local SQLite files and credentials.
Azure startup now requires `DELIVERY360_AZURE_SQL_CONNECTION_STRING`; a missing
setting causes an explicit startup error rather than SQLite fallback.

To rebuild: run `npm run build` in `frontend`, then run `./package-azure.ps1`
from the project directory.

The request names the App Service `deliver360`; the older instructions below name
`delivery360`. Use your actual existing App Service name. For `deliver360` in
resource group `Practice`, run these commands in Azure Cloud Shell (Bash):

```bash
az webapp config set -g Practice -n deliver360 --startup-file "sh startup.sh"
az webapp config appsettings set -g Practice -n deliver360 --settings SCM_DO_BUILD_DURING_DEPLOYMENT=true PORT=8000 DELIVERY360_COOKIE_SECURE=true DELIVERY360_AZURE_SQL_INIT_SCHEMA=false
az webapp deploy -g Practice -n deliver360 --src-path delivery360-azure-sql.zip --type zip --track-status false
```

Before deploying, set `OPENAI_API_KEY` and the secret
`DELIVERY360_AZURE_SQL_CONNECTION_STRING` in App Service environment variables.
For the documented system-assigned managed identity connection:

```text
Server=tcp:delivery360server.database.windows.net,1433;Database=delivery360;Authentication=ActiveDirectoryMSI;Encrypt=yes;TrustServerCertificate=no;
```

Enable the App Service identity, grant its database user `db_datareader` and
`db_datawriter`, and allow network access from App Service to SQL. The destination
must already contain the schema, business rows, and users. Packaging does not
migrate data: use `migrate_sqlite_to_azure.py` with access to the original `state/`
directory to import/verify both databases before switching traffic.

The existing demo-auth guard still applies: for an IP-restricted POC only, explicitly
set `DELIVERY360_ALLOW_INSECURE_DEMO_AUTH=true`. Enterprise authentication is not
implemented by this package. A public deployment requires authentication work.

The package has been checked locally; a live Azure SQL connection must be verified
in your environment using your configured identity and network access.

## Original manual packaging procedure

Step-1  Build The React Front End
cd frontend
npm install
npm run build
cd ..
Verify the build:
Test-Path .\frontend\dist\index.html
Expected result: True.
Step 2 — Create the Linux-compatible deployment ZIP
move to the root directory
C:\Users\faheem\projects\Delivery360_Web\Delivery360_React_FastAPI_MultiUser_Persistence_v2
Creat the ZIP

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$root = (Get-Location).Path
$stage = Join-Path $root "deploy-staging"
$zipPath = Join-Path $root "delivery360-multiuser-v2.zip"

# Clean staging
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory $stage | Out-Null

# Copy Python application files
Copy-Item "$root\*.py" $stage
Copy-Item "$root\requirements.txt" $stage
Copy-Item "$root\startup.sh" $stage

# Copy source data if available
if (Test-Path "$root\data") {
    Copy-Item "$root\data" "$stage\data" -Recurse
}

# Copy compiled React application
New-Item -ItemType Directory "$stage\frontend" | Out-Null
Copy-Item "$root\frontend\dist" "$stage\frontend\dist" -Recurse

# Validate required files
$required = @(
    "backend.py",
    "delivery360_core.py",
    "requirements.txt",
    "frontend\dist\index.html"
)

foreach ($file in $required) {
    if (-not (Test-Path (Join-Path $stage $file))) {
        throw "Missing deployment file: $file"
    }
}

# Create Linux-compatible ZIP
Remove-Item $zipPath -Force -ErrorAction SilentlyContinue

$archive = [System.IO.Compression.ZipFile]::Open(
    $zipPath,
    [System.IO.Compression.ZipArchiveMode]::Create
)

try {
    Get-ChildItem $stage -Recurse -File | ForEach-Object {
        $relative = $_.FullName.Substring($stage.Length + 1).Replace('\', '/')

        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive,
            $_.FullName,
            $relative,
            [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
    }
}
finally {
    $archive.Dispose()
}

Write-Host "Created: $zipPath"

Step-4 Verify the Zip Structure
$archive = [System.IO.Compression.ZipFile]::OpenRead(
    (Resolve-Path .\delivery360-multiuser-v2.zip).Path
)

$entries = @($archive.Entries.FullName)

Write-Host "Backend included:" ($entries -contains "backend.py")
Write-Host "React included:" ($entries -contains "frontend/dist/index.html")
Write-Host "Linux paths valid:" (@($entries | Where-Object { $_.Contains('\') }).Count -eq 0)

$archive.Dispose()

------------------------------------
All three results should be True.
------------------------------------
Step 5 — Configure Azure application settings
Open Azure Portal → App Services → delivery360 → Settings → Environment variables.
Configure the following:
Setting	Value
OPENAI_API_KEY	Your OpenAI API key
PORT	8000
SCM_DO_BUILD_DURING_DEPLOYMENT	true
DELIVERY360_AZURE_SQL_CONNECTION_STRING	Encrypted Azure SQL connection string for database delivery360
DELIVERY360_COOKIE_SECURE	true
Store the connection string as a secret App Service setting. Prefer the App Service managed identity after enabling the identity and creating its database user. For this app's runtime, grant that user `db_datareader` and `db_datawriter`; leave `DELIVERY360_AZURE_SQL_INIT_SCHEMA` unset/false because the schema is already created. For first-time schema provisioning only, enable that setting temporarily with a principal allowed to create and alter `dbo` tables. A system-assigned identity connection string is `Server=tcp:delivery360server.database.windows.net,1433;Database=delivery360;Authentication=ActiveDirectoryMSI;Encrypt=yes;TrustServerCertificate=no;`. The Python Azure SQL driver is included in `requirements.txt` and does not need a separately installed ODBC driver.

To migrate or verify both local databases, run `migrate_sqlite_to_azure.py` from the project root with `DELIVERY360_AZURE_SQL_CONNECTION_STRING` set to the target database connection string. The migration inserts only when all destination tables are empty; if the migration has already run, it verifies exact row equality and reports the counts without duplicating data. It stops on partial or mismatched destination contents.
For authentication, there is an additional decision:
Recommended: Configure enterprise authentication before exposing the application to other users.
Temporary POC alternative: If you need to validate the existing local demo login on Azure, first restrict App Service network access to your approved IP address, then enable DELIVERY360_ALLOW_INSECURE_DEMO_AUTH=true for testing. Do not use this configuration for a public deployment.
Step 6 — Upload and deploy
In Azure Cloud Shell (Bash), upload delivery360-multiuser-v2.zip.
Then run:
az webapp deploy \
  --resource-group Practice \
  --name delivery360 \
  --src-path delivery360-multiuser-v2.zip \
  --type zip

  Restart after deployment if necessary:
  az webapp restart -g Practice -n delivery360
