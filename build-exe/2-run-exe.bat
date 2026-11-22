@echo off
chcp 65001 >nul
title run built package
set "EXE=%~dp0dist\fundflow\fundflow.exe"
if not exist "%EXE%" (
  echo Not built yet. Run 1-build.bat first.
  pause
  exit /b 1
)
start "" "%EXE%"
