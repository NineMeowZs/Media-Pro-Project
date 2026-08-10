@echo off
title MediaPro Launcher
echo Launching MediaPro Video Editor...
cd /d "D:\Folder_For_Work\Year4_1\Media Pro Project\Program"
python app.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to start. Make sure Python is in your PATH.
    pause
)
