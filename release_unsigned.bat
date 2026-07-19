@echo off
REM 未签名开发发版（不需要 WINDOWS_CERTIFICATE）
REM   release_unsigned.bat
REM   release_unsigned.bat 0.5.0
cd /d "%~dp0"
python trigger_release_unsigned.py %*
if errorlevel 1 pause
