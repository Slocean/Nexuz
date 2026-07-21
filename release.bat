@echo off
REM 本地触发 GitHub 打包发版（不需要 gh / 代码签名证书）
REM   release.bat
REM   release.bat 0.5.3
cd /d "%~dp0"
python trigger_release.py %*
if errorlevel 1 pause
