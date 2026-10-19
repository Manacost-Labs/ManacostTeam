param(
    [ValidateSet('Start', 'Stop', 'Status', 'Env')][string]$Action = 'Start',
    [string]$RuntimeRoot = (Join-Path $PSScriptRoot '..\..\build\editor-windows-tools')
)
$ErrorActionPreference = 'Stop'
$runtime = (Resolve-Path -LiteralPath $RuntimeRoot).Path
$stateFile = Join-Path $runtime 'running.json'
$environment = Get-Content -Raw -LiteralPath (Join-Path $runtime 'environment.json') | ConvertFrom-Json
foreach ($item in $environment.PSObject.Properties) {
    [Environment]::SetEnvironmentVariable($item.Name, [string]$item.Value, 'Process')
}
if ($Action -eq 'Env') { return }

function Get-OwnedProcess($record) {
    $process = Get-Process -Id $record.pid -ErrorAction SilentlyContinue
    if ($process -and $process.Path -eq $record.exe -and $process.StartTime.ToUniversalTime().Ticks.ToString() -eq $record.created) {
        return $process
    }
    return $null
}

$records = @()
if (Test-Path -LiteralPath $stateFile) {
    $records = @(Get-Content -Raw -LiteralPath $stateFile | ConvertFrom-Json)
}
if ($Action -eq 'Stop') {
    foreach ($record in $records) {
        $process = Get-OwnedProcess $record
        if ($process) {
            $process | Stop-Process
            if (-not $process.WaitForExit(10000)) { throw "Process $($record.pid) did not stop." }
        }
    }
    '[]' | Set-Content -LiteralPath $stateFile -Encoding UTF8
    Write-Output 'Stopped owned analyzer services.'
    return
}
if ($Action -eq 'Status') {
    foreach ($record in $records) {
        [PSCustomObject]@{ Name = $record.name; Pid = $record.pid; Running = [bool](Get-OwnedProcess $record) }
    }
    return
}

$started = @()
try {
    $services = Get-Content -Raw -LiteralPath (Join-Path $runtime 'services.json') | ConvertFrom-Json
    foreach ($service in $services) {
        $record = $records | Where-Object { $_.name -eq $service.name } | Select-Object -First 1
        if ($record -and (Get-OwnedProcess $record)) { continue }
        $socket = [Net.Sockets.TcpClient]::new()
        try { $socket.Connect('127.0.0.1', [int]$service.port); $occupied = $true }
        catch { $occupied = $false }
        finally { $socket.Dispose() }
        if ($occupied) { throw "Port $($service.port) is already owned by another service." }
        # Start-Process joins ArgumentList; quote every path/argument explicitly.
        $arguments = @($service.args | ForEach-Object {
            if ($_ -match '["\r\n]' -or $_.EndsWith('\')) { throw 'Unsupported process argument' }
            '"' + $_ + '"'
        })
        $process = Start-Process -FilePath $service.exe -ArgumentList $arguments -WorkingDirectory $runtime -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime "$($service.name).stdout.log") -RedirectStandardError (Join-Path $runtime "$($service.name).stderr.log")
        # Process.Path can briefly be null immediately after Start-Process.
        # Record the exact executable we launched; later ownership checks still
        # require both the live path and the original process creation time.
        $entry = [PSCustomObject]@{ name = $service.name; pid = $process.Id; exe = (Resolve-Path -LiteralPath $service.exe).Path; created = $process.StartTime.ToUniversalTime().Ticks.ToString() }
        $started += $entry
        $records = @($records | Where-Object { $_.name -ne $entry.name }) + $entry
        ConvertTo-Json -InputObject @($records) | Set-Content -LiteralPath $stateFile -Encoding UTF8
    }
    $deadline = (Get-Date).AddSeconds(90)
    do {
        $ready = $false
        try {
            $nlp = Invoke-RestMethod -Uri "$env:NATASHA_URL/health" -TimeoutSec 5
            $lt = Invoke-RestMethod -Method Post -Uri "$env:LANGUAGETOOL_URL/v2/check" -Body @{ language = 'ru-RU'; text = 'Простой тест.' } -TimeoutSec 5
            $ready = $nlp.complete -and $nlp.natasha.status -eq 'ok' -and $null -ne $lt.software
        } catch { Start-Sleep -Milliseconds 500 }
    } until ($ready -or (Get-Date) -gt $deadline)
    if (-not $ready) { throw 'Analyzer startup did not reach full health; see local logs.' }
    Write-Output 'Natasha and LanguageTool ready on loopback; analyzer environment loaded.'
} catch {
    foreach ($record in $started) {
        $process = Get-OwnedProcess $record
        if ($process) {
            $process | Stop-Process
            $process.WaitForExit(10000) | Out-Null
        }
    }
    throw
}
