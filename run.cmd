@echo off
title PBI Indexer - Offline Consolidation and Mapping Tool
cd /d "%~dp0"

echo ========================================================
echo Starting PBI Indexer Tool...
echo ========================================================

python main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Application exited with code %ERRORLEVEL%.
    pause
)
