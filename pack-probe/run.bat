@echo off
chcp 65001 >nul
title fundflow probe
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0probe.ps1"
pause
