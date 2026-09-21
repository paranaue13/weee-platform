$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\backend"
if (-not (Test-Path ".venv")) { py -3 -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
& .\.venv\Scripts\pyinstaller.exe --noconfirm --clean --name WEEEPlatformServer --add-data "app\static;app\static" --add-data "uploads;uploads" --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto launcher.py
Write-Host "Build created under backend\dist\WEEEPlatformServer"
