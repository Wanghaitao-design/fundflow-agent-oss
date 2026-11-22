@echo off
chcp 65001 >nul
title PC env setup
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pc-setup.ps1"
pause
