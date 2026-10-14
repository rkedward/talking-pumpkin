# Stops the pumpkin: its brain (main.py, with the Python process it starts) and the browser windows
# start.ps1 opened.
param([switch]$Quiet)
$Root = Split-Path -Parent $PSScriptRoot
$all = Get-CimInstance Win32_Process
$brains = $all | Where-Object { $_.CommandLine -like "*main.py*" -and $_.CommandLine -like "*$Root*" }
foreach ($p in $brains) { taskkill /PID $p.ProcessId /T /F 2>$null | Out-Null }   # /T: the venv's child python too
$pages = $all | Where-Object { $_.CommandLine -like "*pumpkin-face*" -or $_.CommandLine -like "*pumpkin-window*" -or $_.CommandLine -like "*pumpkin-debug*" }
foreach ($p in $pages) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
if (-not $Quiet) { Write-Host "Pumpkin stopped." }
