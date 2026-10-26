$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$projectRoot = $PSScriptRoot
$zipPath = Join-Path $projectRoot 'delivery360-azure-sql.zip'
$files = @('backend.py', 'azure_sql.py', 'context_service.py', 'delivery360_core.py',
    'migrate_sqlite_to_azure.py', 'requirements.txt', 'startup.sh')
foreach ($directory in @('data', 'frontend/dist')) {
    $files += @(Get-ChildItem (Join-Path $projectRoot $directory) -Recurse -File | ForEach-Object {
        $_.FullName.Substring($projectRoot.Length + 1).Replace('\', '/')
    })
}
foreach ($file in ($files + @('frontend/dist/index.html'))) {
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $file) -PathType Leaf)) {
        throw "Missing deployment file: $file. Run npm run build in frontend first."
    }
}
$stream = [System.IO.File]::Open($zipPath, [System.IO.FileMode]::Create)
$archive = New-Object System.IO.Compression.ZipArchive($stream, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($file in $files) {
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive, (Join-Path $projectRoot $file), $file,
            [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
} finally {
    $archive.Dispose()
    $stream.Dispose()
}
$archive = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    $entries = @($archive.Entries.FullName)
    foreach ($required in @('backend.py', 'azure_sql.py', 'startup.sh', 'requirements.txt', 'frontend/dist/index.html')) {
        if ($entries -notcontains $required) { throw "ZIP missing: $required" }
    }
    if (@($entries | Where-Object { $_.Contains('\') }).Count) { throw 'ZIP contains Windows paths' }
    Write-Host "Validated $($entries.Count) files: $zipPath"
} finally { $archive.Dispose() }
