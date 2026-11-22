@echo off
chcp 65001 >nul
title build officer package
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-officer.ps1"
echo.
echo report file: %~dp0build-report.txt
pause
