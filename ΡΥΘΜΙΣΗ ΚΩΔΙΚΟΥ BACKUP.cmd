@echo off
chcp 65001 >nul
cd /d "%~dp0backend\scripts"
"..\.venv\Scripts\python.exe" setup_backup_key.py
pause
