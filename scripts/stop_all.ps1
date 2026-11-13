param([switch]$Quiet)

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$dataDirectory = Join-Path $repositoryRoot 'data'
$statePath = Join-Path $dataDirectory 'start_all_processes.json'

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

function Test-SameProcess {
    param($Current, $Recorded)

    if ($null -eq $Current -or $null -eq $Recorded) {
        return $false
    }
    return (
        [int]$Current.ProcessId -eq [int]$Recorded.processId -and
        [string]$Current.Name -eq [string]$Recorded.name -and
        (Get-CreationTimestamp $Current) -eq [string]$Recorded.creationTime -and
        [string]$Current.CommandLine -eq [string]$Recorded.commandLine
    )
}

if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
    if (-not $Quiet) {
        Write-Output 'No SkyWarden launcher state found; no processes were stopped.'
    }
    return
}

$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if ($state.owner -ne 'SkyWarden start_all.ps1') {
    throw "Refusing to use unrecognized process state at $statePath."
}

$currentProcesses = @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop)
$currentById = @{}
foreach ($process in $currentProcesses) {
    $currentById[[string][int]$process.ProcessId] = $process
}

$recordedById = @{}
foreach ($recorded in @($state.processes)) {
    $recordedById[[string][int]$recorded.processId] = $recorded
}

$processesToStop = @{}
foreach ($recorded in @($state.processes)) {
    $key = [string][int]$recorded.processId
    $current = $currentById[$key]
    if (Test-SameProcess -Current $current -Recorded $recorded) {
        $processesToStop[$key] = [pscustomobject]@{
            process = $current
            depth = [int]$recorded.depth
        }
    }
}

$verifiedRoots = @{}
foreach ($rootProcessId in @($state.rootProcessIds)) {
    $key = [string][int]$rootProcessId
    $recordedRoot = $recordedById[$key]
    $currentRoot = $currentById[$key]
    if (Test-SameProcess -Current $currentRoot -Recorded $recordedRoot) {
        $verifiedRoots[$key] = [pscustomobject]@{
            process = $currentRoot
            depth = 0
        }
    }
}

$changed = $true
while ($changed) {
    $changed = $false
    foreach ($process in $currentProcesses) {
        $processId = [int]$process.ProcessId
        $parentId = [string][int]$process.ParentProcessId
        $processKey = [string]$processId
        if ($verifiedRoots.ContainsKey($parentId) -and -not $verifiedRoots.ContainsKey($processKey)) {
            $verifiedRoots[$processKey] = [pscustomobject]@{
                process = $process
                depth = [int]$verifiedRoots[$parentId].depth + 1
            }
            $changed = $true
        }
    }
}
foreach ($key in $verifiedRoots.Keys) {
    if (-not $processesToStop.ContainsKey($key)) {
        $processesToStop[$key] = $verifiedRoots[$key]
    }
}

$orderedProcesses = @($processesToStop.Values | Sort-Object -Property depth -Descending)
foreach ($entry in $orderedProcesses) {
    $processId = [int]$entry.process.ProcessId
    try {
        Stop-Process -Id $processId -Force -ErrorAction Stop
        if (-not $Quiet) {
            Write-Output "Stopped managed process $processId ($($entry.process.Name))."
        }
    }
    catch {
        $stillRunning = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
        if ($stillRunning -and (Test-SameProcess -Current $stillRunning -Recorded $recordedById[[string]$processId])) {
            throw "Could not stop managed process ${processId}: $($_.Exception.Message)"
        }
    }
}

foreach ($entry in $orderedProcesses) {
    $processId = [int]$entry.process.ProcessId
    $stillRunning = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
    if ($stillRunning -and (Get-CreationTimestamp $stillRunning) -eq (Get-CreationTimestamp $entry.process)) {
        throw "Managed process $processId is still running; launcher state was retained."
    }
}

Remove-Item -LiteralPath $statePath -Force
if (Test-Path -LiteralPath "$statePath.tmp") {
    Remove-Item -LiteralPath "$statePath.tmp" -Force
}
if (-not $Quiet) {
    Write-Output 'Stopped the SkyWarden processes recorded by start_all.ps1.'
}
