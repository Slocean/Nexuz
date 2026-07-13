@echo off
setlocal
cd /d "%~dp0"

echo === Nexuz package ===
python package.py %*
if errorlevel 1 (
  echo.
  echo Package failed.
  exit /b 1
)

echo.
echo Done. Output under dist\
exit /b 0
