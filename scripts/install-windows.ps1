# Bootstrap the Jarvis at Work client on a Windows machine.
#   powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "Creating virtualenv..." -ForegroundColor Cyan
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r requirements.txt

if (-not (Test-Path config.yaml)) {
    Copy-Item config.example.yaml config.yaml
    Write-Host "Created config.yaml — edit blind_apps before first run." -ForegroundColor Yellow
}

Write-Host "`nDone. Next:" -ForegroundColor Green
Write-Host "  1. Edit config.yaml (blind_apps / blind_title_patterns)"
Write-Host "  2. setx ANTHROPIC_API_KEY sk-ant-..."
Write-Host "  3. .\.venv\Scripts\python -m jarvis_work.daemon.app"
Write-Host "  4. Wire the MCP shim into claude_desktop_config.json (docs\INSTALL-WINDOWS.md)"
