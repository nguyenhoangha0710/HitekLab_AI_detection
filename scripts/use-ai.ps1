<#
.SYNOPSIS
  Chon noi chay AI Service (CPU / GPU may nay / GPU truong qua SSH / tat) va khoi dong lai Docker.

.DESCRIPTION
  Script tu sua cac dong lien quan trong .env (COMPOSE_PROFILES, COMPOSE_FILE, AI_SERVICE_WS_URL,
  YOLO_DEVICE, EDGE_MODE, AI_FPS, EDGE_AI_QUEUE_SIZE), giu nguyen cac dong khac va profile "backend"
  neu dang bat, roi chay docker compose. Cuoi cung goi /health de in ra AI dang chay o dau.

.EXAMPLE
  .\scripts\use-ai.ps1 status   # dang o che do nao, AI chay o dau (CPU/GPU, may nao)
  .\scripts\use-ai.ps1 cpu      # AI trong Docker, chay CPU (may nao cung chay duoc, cham)
  .\scripts\use-ai.ps1 gpu      # AI trong Docker, chay GPU NVIDIA cua chinh may nay
  .\scripts\use-ai.ps1 remote   # AI chay tren server GPU truong (khoa-gpu) qua SSH tunnel cua VS Code
  .\scripts\use-ai.ps1 off      # khong chay AI, chi xem video
  .\scripts\use-ai.ps1 remote -NoRestart   # chi sua .env, khong khoi dong lai Docker
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet("status", "cpu", "gpu", "remote", "off")]
    [string]$Mode = "status",
    [switch]$NoRestart
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $root ".env"
Set-Location $root

if (-not (Test-Path $envPath)) {
    Copy-Item (Join-Path $root ".env.example") $envPath
    Write-Host "Da tao .env tu .env.example" -ForegroundColor Yellow
}

function Read-EnvLines { return , [System.IO.File]::ReadAllLines($envPath) }

function Get-EnvValue([string[]]$Lines, [string]$Key) {
    foreach ($line in $Lines) {
        if ($line -match "^\s*$([regex]::Escape($Key))\s*=(.*)$") { return $Matches[1].Trim() }
    }
    return $null
}

function Set-EnvValues([hashtable]$Values) {
    $lines = [System.Collections.Generic.List[string]]::new()
    $done = @{}
    foreach ($line in (Read-EnvLines)) {
        $replaced = $false
        foreach ($key in $Values.Keys) {
            if ($line -match "^\s*$([regex]::Escape($key))\s*=") {
                if (-not $done.ContainsKey($key)) { $lines.Add("$key=$($Values[$key])") }
                $done[$key] = $true
                $replaced = $true
                break
            }
        }
        if (-not $replaced) { $lines.Add($line) }
    }
    foreach ($key in $Values.Keys) {
        if (-not $done.ContainsKey($key)) { $lines.Add("$key=$($Values[$key])") }
    }
    # UTF-8 khong BOM de docker compose doc dung dong dau tien
    [System.IO.File]::WriteAllLines($envPath, $lines, [System.Text.UTF8Encoding]::new($false))
}

function Test-LocalPort([int]$Port) {
    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $ok = $client.ConnectAsync("127.0.0.1", $Port).Wait(1500)
        $client.Dispose()
        return $ok
    }
    catch { return $false }
}

function Get-CurrentMode([string[]]$Lines) {
    if ((Get-EnvValue $Lines "EDGE_MODE") -eq "viewer") { return "off" }
    $url = Get-EnvValue $Lines "AI_SERVICE_WS_URL"
    if ($url -and $url -like "*host.docker.internal*") { return "remote" }
    $files = Get-EnvValue $Lines "COMPOSE_FILE"
    if ($files -and $files -like "*docker-compose.gpu.yml*") { return "gpu" }
    return "cpu"
}

function Show-Status {
    $lines = Read-EnvLines
    $mode = Get-CurrentMode $lines
    $port = Get-EnvValue $lines "AI_SERVICE_PORT"
    if (-not $port) { $port = "8003" }
    $labels = @{
        cpu    = "AI trong Docker - CPU (cham)"
        gpu    = "AI trong Docker - GPU may nay"
        remote = "AI tren server GPU truong qua SSH tunnel"
        off    = "Khong chay AI (chi video)"
    }
    Write-Host ""
    Write-Host "Che do trong .env : $mode  ($($labels[$mode]))" -ForegroundColor Cyan
    Write-Host "COMPOSE_PROFILES  : $(Get-EnvValue $lines 'COMPOSE_PROFILES')"
    Write-Host "AI_SERVICE_WS_URL : $(Get-EnvValue $lines 'AI_SERVICE_WS_URL')"
    if ($mode -eq "off") { return }
    try {
        $health = Invoke-RestMethod -Uri "http://localhost:$port/health" -TimeoutSec 5
        $rt = $health.runtime
        if (-not $rt) {
            Write-Host "AI dang chay (ban cu, chua bao runtime): device=$($health.device)" -ForegroundColor Yellow
            return
        }
        $color = if ($rt.accelerator -eq "gpu") { "Green" } else { "Yellow" }
        Write-Host ("AI dang chay      : {0} {1} @ {2} (torch {3})" -f $rt.accelerator.ToUpper(), $rt.device_name, $rt.host, $rt.torch) -ForegroundColor $color
    }
    catch {
        Write-Host "AI chua tra loi tai http://localhost:$port/health" -ForegroundColor Red
        if ($mode -eq "remote") {
            Write-Host "  - VS Code da ket noi khoa-gpu chua? (~/.ssh/config can LocalForward 8003 / RemoteForward 18010)"
            Write-Host "  - AI da chay tren server chua? (tren server: bash scripts/run_ai_remote.sh)"
        }
        else {
            Write-Host "  - Doi 20-60 giay de container khoi dong, hoac xem: docker compose logs --tail 50 ai-service"
        }
    }
}

if ($Mode -eq "status") { Show-Status; exit 0 }

$lines = Read-EnvLines
$profiles = Get-EnvValue $lines "COMPOSE_PROFILES"
$hasBackend = $profiles -and (($profiles -split ",") | ForEach-Object { $_.Trim() }) -contains "backend"
function Join-Profiles([bool]$WithAi) {
    $list = @()
    if ($WithAi) { $list += "ai" }
    if ($hasBackend) { $list += "backend" }
    return ($list -join ",")
}

switch ($Mode) {
    "cpu" {
        Set-EnvValues @{
            COMPOSE_PROFILES       = (Join-Profiles $true)
            COMPOSE_FILE           = "docker-compose.yml"
            AI_SERVICE_WS_URL      = "ws://ai-service:8003/ws/detect"
            YOLO_DEVICE            = "cpu"
            EDGE_MODE              = "viewer-ai"
            AI_FPS                 = "2"
            EDGE_AI_QUEUE_SIZE     = "1"
        }
    }
    "gpu" {
        Set-EnvValues @{
            COMPOSE_PROFILES       = (Join-Profiles $true)
            COMPOSE_PATH_SEPARATOR = ";"
            COMPOSE_FILE           = "docker-compose.yml;docker-compose.gpu.yml"
            AI_SERVICE_WS_URL      = "ws://ai-service:8003/ws/detect"
            YOLO_DEVICE            = "0"
            EDGE_MODE              = "viewer-ai"
            AI_FPS                 = "5"
            EDGE_AI_QUEUE_SIZE     = "1"
        }
    }
    "remote" {
        Set-EnvValues @{
            COMPOSE_PROFILES       = (Join-Profiles $false)
            COMPOSE_FILE           = "docker-compose.yml"
            AI_SERVICE_WS_URL      = "ws://host.docker.internal:8003/ws/detect"
            EDGE_MODE              = "viewer-ai"
            AI_FPS                 = "5"
            EDGE_AI_QUEUE_SIZE     = "1"
        }
        if (-not (Test-LocalPort 8003)) {
            Write-Host "Canh bao: cong 8003 tren may nay chua mo. Ket noi VS Code toi khoa-gpu va chay AI tren server truoc." -ForegroundColor Yellow
        }
    }
    "off" {
        Set-EnvValues @{
            COMPOSE_PROFILES       = (Join-Profiles $false)
            COMPOSE_FILE           = "docker-compose.yml"
            EDGE_MODE              = "viewer"
        }
    }
}
Write-Host "Da cap nhat .env -> che do '$Mode'" -ForegroundColor Cyan

if (-not $NoRestart) {
    if ($Mode -in @("remote", "off")) {
        # Tat AI chay trong Docker (neu dang chay) de khong ton CPU/GPU may nay
        & { $ErrorActionPreference = "Continue"; docker compose --profile ai stop ai-service *> $null }
    }
    docker compose up -d --build
    if ($LASTEXITCODE -ne 0) { throw "docker compose up that bai" }
    Write-Host "Doi he thong khoi dong..." -ForegroundColor DarkGray
    Start-Sleep -Seconds 8
}
Show-Status
