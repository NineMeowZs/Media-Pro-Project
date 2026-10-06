@echo off
title MediaPro Video Editor - Launcher
cd /d "%~dp0"
echo ========================================================
echo   MediaPro Video Editor - Starting Application...
echo ========================================================
python app.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with error code %ERRORLEVEL%.
    pause
)
