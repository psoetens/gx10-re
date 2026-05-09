<#
Helper for the windows-bts-captures branch tasks.

Usage (in an ELEVATED PowerShell):
  .\tools\bts_capture.ps1 -Topic startup [-Interface USBPcap1] [-Seconds 0]

  -Topic       short name; output goes to captures/bts_<topic>/<topic>.pcap
  -Interface   USBPcap interface; auto-detects if omitted (default USBPcap1)
  -Seconds     auto-stop after N seconds (default 0 = stop with Ctrl+C)

After capture completes the script runs:
  python tools\pcap_to_jsonl.py <pcap>     -> <topic>.jsonl
  python tools\sysex_decode.py  <jsonl>    -> <topic>_decoded.txt

#>
param(
    [Parameter(Mandatory=$true)]
    [string]$Topic,
    [string]$Interface = "USBPcap1",
    [int]$Seconds = 0
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Need admin
$cur = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $cur.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERROR: USBPcap requires admin. Re-run from an elevated PowerShell:" -ForegroundColor Red
    Write-Host "  Right-click PowerShell -> Run as administrator"
    Write-Host "  cd '$root'"
    Write-Host "  .\tools\bts_capture.ps1 -Topic $Topic"
    exit 1
}

$captureDir = Join-Path $root "captures\bts_$Topic"
New-Item -ItemType Directory -Path $captureDir -Force | Out-Null
$pcap   = Join-Path $captureDir "$Topic.pcap"
$jsonl  = Join-Path $captureDir "$Topic.jsonl"
$decoded= Join-Path $captureDir "$Topic`_decoded.txt"
$summary= Join-Path $root "captures\bts_$Topic.summary.md"

Write-Host "=== USBPcap capture ==="
Write-Host "  topic:     $Topic"
Write-Host "  interface: $Interface"
Write-Host "  pcap:      $pcap"
Write-Host ""

# Build command
$usbpcap = "C:\Program Files\USBPcap\USBPcapCMD.exe"
$args = @("-d", "\\.\$Interface", "-A", "-o", $pcap)

Write-Host "Starting capture. Perform the BTS action, then press Ctrl+C in this window."
if ($Seconds -gt 0) {
    Write-Host "(will auto-stop after $Seconds seconds)"
    $proc = Start-Process -FilePath $usbpcap -ArgumentList $args -PassThru -NoNewWindow
    Start-Sleep -Seconds $Seconds
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
} else {
    & $usbpcap @args
}

Write-Host ""
Write-Host "Capture stopped. File: $pcap"
if (-not (Test-Path $pcap)) {
    Write-Host "ERROR: No pcap was created. Try a different USBPcap interface (USBPcap2..6)." -ForegroundColor Red
    exit 2
}
$size = (Get-Item $pcap).Length
Write-Host "  size: $([math]::Round($size/1KB,1)) KB"
if ($size -lt 1000) {
    Write-Host "WARNING: pcap is unusually small. Likely the wrong interface." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Convert pcap -> JSONL ==="
& python tools\pcap_to_jsonl.py $pcap > $jsonl
$jsonlSize = (Get-Item $jsonl).Length
Write-Host "  $jsonl  ($([math]::Round($jsonlSize/1KB,1)) KB)"

Write-Host ""
Write-Host "=== Decode JSONL ==="
& python tools\sysex_decode.py $jsonl > $decoded
$decSize = (Get-Item $decoded).Length
Write-Host "  $decoded  ($([math]::Round($decSize/1KB,1)) KB)"

Write-Host ""
Write-Host "=== Quick stats ==="
$lines = Get-Content $jsonl
Write-Host "  $($lines.Count) JSONL events"
$sysexCount = ($lines | Where-Object { $_ -match '"sysex"' }).Count
Write-Host "  $sysexCount sysex events"

Write-Host ""
Write-Host "Next: open $decoded and curate $summary with the decisive 5-20 events."
