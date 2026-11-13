$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$uiDirectory = Join-Path $repositoryRoot 'ui'

if (-not (Test-Path (Join-Path $uiDirectory 'package.json'))) {
    throw "UI project not found at $uiDirectory."
}
if (-not (Test-Path (Join-Path $uiDirectory 'node_modules'))) {
    throw "Install UI dependencies first with 'Set-Location ui; npm ci'."
}

Push-Location $uiDirectory
try {
    npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
    if ($LASTEXITCODE -ne 0) {
        throw "Vite exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
