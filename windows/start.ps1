# Starts the pumpkin on a Windows laptop: the brain (main.py) in the background, the face full screen on
# the projector, the debug panel on the laptop's own screen, and a side-show window on a spare HDMI display
# if one is set up. The face goes on the first display that isn't the laptop screen (or [face] screen).

$ProgressPreference = "SilentlyContinue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
& (Join-Path $PSScriptRoot "stop.ps1") -Quiet

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { Write-Host "Run windows\install.bat first."; Read-Host "Press Enter to close"; exit 1 }
$info = (& $Py windows\launch_info.py) | ConvertFrom-Json
$url = "http://localhost:$($info.port)"

New-Item -ItemType Directory -Force "logs" | Out-Null
$brain = Start-Process -FilePath $Py -ArgumentList "-u", "main.py" -WorkingDirectory $Root -WindowStyle Hidden `
    -RedirectStandardOutput "logs\pumpkin.log" -RedirectStandardError "logs\pumpkin-errors.log" -PassThru
Write-Host "Starting the pumpkin..."
$up = $false
for ($i = 0; $i -lt 90 -and -not $up; $i++) {
    Start-Sleep -Seconds 1
    if ($brain.HasExited) { break }
    try { Invoke-WebRequest "$url/" -UseBasicParsing -TimeoutSec 2 | Out-Null; $up = $true } catch { }
}
if (-not $up) {
    Write-Host "The pumpkin didn't start. Last lines of logs\pumpkin-errors.log:" -ForegroundColor Red
    if (Test-Path "logs\pumpkin-errors.log") { Get-Content "logs\pumpkin-errors.log" -Tail 20 }
    Read-Host "Press Enter to close"
    exit 1
}

# Chrome if installed, otherwise Edge (comes with Windows)
$browser = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $browser) { Write-Host "Install Google Chrome or Microsoft Edge."; Read-Host "Press Enter to close"; exit 1 }

Add-Type -AssemblyName System.Windows.Forms
$screens = @([System.Windows.Forms.Screen]::AllScreens)
$main = $screens | Where-Object { $_.Primary } | Select-Object -First 1
$others = @($screens | Where-Object { -not $_.Primary })
if ($info.face_screen -ge 1 -and $info.face_screen -le $screens.Count) { $faceScreen = $screens[$info.face_screen - 1] }
elseif ($others.Count -ge 1) { $faceScreen = $others[0] }
else { $faceScreen = $main }

function Open-Page($page, $screen, $dataDir, [switch]$Full) {
    $b = $screen.Bounds
    $flags = @("--app=$url/$page", "--user-data-dir=$env:TEMP\$dataDir", "--window-position=$($b.X),$($b.Y)",
              "--no-first-run", "--noerrdialogs", "--autoplay-policy=no-user-gesture-required", "--disable-features=Translate")
    if ($Full) { $flags += "--start-fullscreen" } else { $flags += "--window-size=1200,800" }
    Start-Process -FilePath $browser -ArgumentList $flags | Out-Null
}

Open-Page "" $faceScreen "pumpkin-face" -Full
if ($info.hdmi_window) {
    $spare = @($others | Where-Object { $_.DeviceName -ne $faceScreen.DeviceName })
    if ($spare.Count -ge 1) { Open-Page "window.html?w=$($info.hdmi_window)" $spare[0] "pumpkin-window" -Full }
    else { Write-Host "No spare display for the '$($info.hdmi_window)' window; open window.html?w=$($info.hdmi_window) on a Wi-Fi projector instead." }
}
if ($faceScreen.DeviceName -ne $main.DeviceName) { Open-Page "?debug" $main "pumpkin-debug" }

Write-Host "The pumpkin is running. Close this window or use 'Stop Pumpkin' to stop it."
Write-Host "Log: $Root\logs\pumpkin.log"
Wait-Process -Id $brain.Id
Write-Host "The pumpkin stopped. Last lines of logs\pumpkin-errors.log:"
if (Test-Path "logs\pumpkin-errors.log") { Get-Content "logs\pumpkin-errors.log" -Tail 20 }
Read-Host "Press Enter to close"
