@echo off
REM 本地触发 GitHub 打包发版（不需要 gh）
REM   release.bat
REM   release.bat 0.1.1
cd /d "%~dp0"
python trigger_release.py %*
if errorlevel 1 pause
