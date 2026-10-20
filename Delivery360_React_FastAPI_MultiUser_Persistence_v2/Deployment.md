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
