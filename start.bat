@echo off
setlocal
cd /d "%~dp0"
echo [Nexuz] one-click dev start...
python dev.py
if errorlevel 1 pause
endlocal
