# Talking Pumpkin: Windows laptop setup. Run it by double-clicking install.bat (safe to run again).
# Installs Python if needed, the pumpkin's Python packages and models, asks for your Claude API key, and
# puts "Talking Pumpkin" and "Stop Pumpkin" shortcuts on the desktop.

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Fail($msg) {
    Write-Host ""
    Write-Host "Setup stopped: $msg" -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

function Find-Python {
    foreach ($v in @("3.12", "3.13", "3.11")) {
        try {
            $exe = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe) { return "$exe".Trim() }
        } catch { }
    }
    return $null
}

Write-Host "== Talking Pumpkin setup" -ForegroundColor DarkYellow

Write-Host "== Python"
$Python = Find-Python
if (-not $Python) {
    Write-Host "Installing Python 3.12 (winget)..."
    winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
    $Python = Find-Python
    if (-not $Python) { Fail "Python didn't install. Install Python 3.12 from python.org, then run install.bat again." }
}
Write-Host "using $Python"

Write-Host "== Python packages (a few minutes the first time)"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail "couldn't create the Python environment." }
}
$Py = Join-Path $Root ".venv\Scripts\python.exe"
& $Py -m pip install --upgrade pip --quiet
& $Py -m pip install -r requirements-windows.txt
if ($LASTEXITCODE -ne 0) { Fail "installing Python packages failed (see the messages above)." }

Write-Host "== Settings"
if (-not (Test-Path "config.toml")) { Copy-Item "config.example.toml" "config.toml" }

Write-Host "== Models (person detector, voice, speech recognition)"
& $Py windows\fetch_models.py
if ($LASTEXITCODE -ne 0) { Fail "downloading the models failed. Check the internet connection and run install.bat again." }

if (-not (Test-Path ".env")) {
    Write-Host ""
    Write-Host "Paste your Claude API key (from console.anthropic.com), or leave it blank to try practice mode first."
    $key = Read-Host "API key"
    if ($key.Trim()) {
        Set-Content -Path ".env" -Value "ANTHROPIC_API_KEY=$($key.Trim())" -Encoding ASCII
    } else {
        Set-Content -Path ".env" -Value "PUMPKIN_FAKE=1" -Encoding ASCII
        Write-Host "Practice mode: add ANTHROPIC_API_KEY=... to $Root\.env later and delete the PUMPKIN_FAKE line."
    }
}

Write-Host "== Shortcuts"
$shell = New-Object -ComObject WScript.Shell
function Add-Shortcut($path, $target, $icon) {
    $s = $shell.CreateShortcut($path)
    $s.TargetPath = Join-Path $Root $target
    $s.WorkingDirectory = $Root
    $s.WindowStyle = 7          # start minimized
    $s.IconLocation = $icon
    $s.Save()
}
$desktop = [Environment]::GetFolderPath("Desktop")
Add-Shortcut (Join-Path $desktop "Talking Pumpkin.lnk") "windows\start.bat" "%SystemRoot%\System32\imageres.dll,186"
Add-Shortcut (Join-Path $desktop "Stop Pumpkin.lnk") "windows\stop.bat" "%SystemRoot%\System32\imageres.dll,93"
$startup = Join-Path ([Environment]::GetFolderPath("Startup")) "Talking Pumpkin.lnk"
$auto = Read-Host "Start the pumpkin automatically when you log in? (y/N)"
if ($auto -match "^[yY]") {
    Add-Shortcut $startup "windows\start.bat" "%SystemRoot%\System32\imageres.dll,186"
    Write-Host "It will start at login. Delete 'Talking Pumpkin' from your Startup folder to stop that."
} elseif (Test-Path $startup) {
    Remove-Item $startup
}

Write-Host ""
Write-Host "All set. Plug in the projector, then double-click 'Talking Pumpkin' on the desktop." -ForegroundColor Green
Write-Host "Windows may ask to allow camera and microphone access, and (for your phone remote) network access: say yes."
Read-Host "Press Enter to close"
