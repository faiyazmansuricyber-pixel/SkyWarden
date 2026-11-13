$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$venvDirectory = Join-Path $repositoryRoot '.venv'
$pythonExecutable = Join-Path $venvDirectory 'Scripts\python.exe'
$activateScript = Join-Path $venvDirectory 'Scripts\Activate.ps1'
$uiDirectory = Join-Path $repositoryRoot 'ui'
$dataDirectory = Join-Path $repositoryRoot 'data'
$logsDirectory = Join-Path $dataDirectory 'logs'
$statePath = Join-Path $dataDirectory 'start_all_processes.json'
$runStamp = Get-Date -Format 'yyyyMMdd-HHmmssfff'
$script:ManagedRootIds = @()

function Get-CreationTimestamp {
    param([Parameter(Mandatory = $true)]$Process)

    $created = $Process.CreationDate
    if ($created -isnot [datetime]) {
        $created = [System.Management.ManagementDateTimeConverter]::ToDateTime(
            [string]$created
        )
    }
    return $created.ToUniversalTime().ToString('o')
}

function Get-ManagedProcessSnapshot {
    $allProcesses = @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop)
    $tracked = @{}
    foreach ($rootProcessId in $script:ManagedRootIds) {
        $rootProcess = $allProcesses |
            Where-Object { [int]$_.ProcessId -eq $rootProcessId } |
            Select-Object -First 1
        if ($null -eq $rootProcess) {
            throw "Could not identify managed process $rootProcessId."
        }
        $tracked[[string]$rootProcessId] = [pscustomobject]@{
            process = $rootProcess
            depth = 0
        }
    }

    $changed = $true
    while ($changed) {
        $changed = $false
        foreach ($process in $allProcesses) {
            $processId = [int]$process.ProcessId
            $parentId = [string][int]$process.ParentProcessId
            $processKey = [string]$processId
            if ($tracked.ContainsKey($parentId) -and -not $tracked.ContainsKey($processKey)) {
                $tracked[$processKey] = [pscustomobject]@{
                    process = $process
                    depth = [int]$tracked[$parentId].depth + 1
                }
                $changed = $true
            }
        }
    }

    foreach ($entry in $tracked.Values) {
        [pscustomobject]@{
            processId = [int]$entry.process.ProcessId
            parentProcessId = [int]$entry.process.ParentProcessId
            name = [string]$entry.process.Name
            creationTime = Get-CreationTimestamp $entry.process
            commandLine = [string]$entry.process.CommandLine
            depth = [int]$entry.depth
        }
    }
}

function Save-ManagedProcessState {
    $state = [pscustomobject]@{
        owner = 'SkyWarden start_all.ps1'
        rootProcessIds = @($script:ManagedRootIds)
        processes = @(Get-ManagedProcessSnapshot)
    }
    $temporaryPath = "$statePath.tmp"
    $state | ConvertTo-Json -Depth 5 |
        Set-Content -LiteralPath $temporaryPath -Encoding UTF8
    Move-Item -LiteralPath $temporaryPath -Destination $statePath -Force
}

function Start-ManagedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$LogName
    )

    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput (Join-Path $logsDirectory "$LogName.stdout.log") `
        -RedirectStandardError (Join-Path $logsDirectory "$LogName.stderr.log") `
        -PassThru
    $script:ManagedRootIds += [int]$process.Id
    Save-ManagedProcessState
    return $process
}

function Wait-ForHttp {
    param(
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [int]$TimeoutSeconds = 90
    )

    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    $lastError = 'No response received.'
    while ($timer.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        $Process.Refresh()
        if ($Process.HasExited) {
            throw "$ServiceName exited before becoming ready. Check data\logs."
        }
        try {
            $response = Invoke-WebRequest -Uri $Uri -Method Get -UseBasicParsing -TimeoutSec 3
            if ([int]$response.StatusCode -eq 200) {
                return
            }
            $lastError = "HTTP $([int]$response.StatusCode)"
        }
        catch {
            $lastError = $_.Exception.Message
        }
        Start-Sleep -Milliseconds 500
    }
    throw "$ServiceName did not respond at $Uri within $TimeoutSeconds seconds. Last result: $lastError"
}

try {
    if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
        throw "Virtual environment Python not found at $pythonExecutable. Create it and install requirements first."
    }
    if (-not (Test-Path -LiteralPath $activateScript -PathType Leaf)) {
        throw "Virtual environment activation script not found at $activateScript."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $uiDirectory 'node_modules') -PathType Container)) {
        throw "UI dependencies are missing. Run 'Set-Location ui; npm ci' first."
    }
    Get-Command npm.cmd -ErrorAction Stop | Out-Null
    if (Test-Path -LiteralPath $statePath) {
        throw "A launcher state file already exists. Run scripts\stop_all.ps1 before starting another demo."
    }

    foreach ($port in @(8001, 9000, 5173)) {
        $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
        if ($listener) {
            throw "Port $port is already listening. Stop the existing service before starting the demo."
        }
    }

    New-Item -ItemType Directory -Path $logsDirectory -Force | Out-Null
    . $activateScript

    Push-Location $repositoryRoot
    try {
        Write-Output 'Resetting and reseeding synthetic SkyVoyage data...'
        & $pythonExecutable -m scripts.reset
        if ($LASTEXITCODE -ne 0) {
            throw "scripts.reset failed with exit code $LASTEXITCODE."
        }

        Write-Output 'Generating synthetic 90-day traffic...'
        & $pythonExecutable -m traffic.generate_logs
        if ($LASTEXITCODE -ne 0) {
            throw "traffic.generate_logs failed with exit code $LASTEXITCODE."
        }

        $targetProcess = Start-ManagedProcess `
            -FilePath $pythonExecutable `
            -ArgumentList @('-m', 'uvicorn', 'target_app.main:app', '--host', '127.0.0.1', '--port', '8001') `
            -WorkingDirectory $repositoryRoot `
            -LogName "target-$runStamp"
        $apiProcess = Start-ManagedProcess `
            -FilePath $pythonExecutable `
            -ArgumentList @('-m', 'uvicorn', 'api.main:app', '--host', '127.0.0.1', '--port', '9000') `
            -WorkingDirectory $repositoryRoot `
            -LogName "api-$runStamp"

        Wait-ForHttp -Process $targetProcess -Uri 'http://127.0.0.1:8001/' -ServiceName 'SkyVoyage'
        Wait-ForHttp -Process $apiProcess -Uri 'http://127.0.0.1:9000/docs' -ServiceName 'Dashboard API'

        Write-Output 'Running safety-gated local recon...'
        & $pythonExecutable -m scripts.recon
        if ($LASTEXITCODE -ne 0) {
            throw "scripts.recon failed with exit code $LASTEXITCODE."
        }

        $uiProcess = Start-ManagedProcess `
            -FilePath $env:ComSpec `
            -ArgumentList @('/d /s /c "npm run dev -- --host 127.0.0.1 --port 5173 --strictPort"') `
            -WorkingDirectory $uiDirectory `
            -LogName "ui-$runStamp"
        Wait-ForHttp -Process $uiProcess -Uri 'http://127.0.0.1:5173/' -ServiceName 'Dashboard UI'
        Save-ManagedProcessState

        Write-Output ''
        Write-Output 'SkyWarden local demo is ready:'
        Write-Output 'Portal:    http://127.0.0.1:8001'
        Write-Output 'API docs:  http://127.0.0.1:9000/docs'
        Write-Output 'Dashboard: http://127.0.0.1:5173'
        Write-Output "Logs:      $logsDirectory"
        Write-Output 'Stop these processes with scripts\stop_all.ps1.'
    }
    finally {
        Pop-Location
    }
}
catch {
    $failure = $_
    if ($script:ManagedRootIds.Count -gt 0) {
        try {
            if (-not (Test-Path -LiteralPath $statePath)) {
                Save-ManagedProcessState
            }
            if (Test-Path -LiteralPath $statePath) {
                & (Join-Path $PSScriptRoot 'stop_all.ps1') -Quiet
            }
        }
        catch {
            Write-Warning "Automatic cleanup failed: $($_.Exception.Message). Run scripts\stop_all.ps1."
        }
    }
    throw $failure
}
