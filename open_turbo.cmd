@echo off
title PBI Indexing Tool - TURBO Blazing Fast Edition
cd /d "%~dp0"

echo ========================================================
echo   PBI Indexing Tool - TURBO / BLAZING FAST EDITION
echo   Powered by DuckDB Vectorized Multi-Threaded C++ Engine
echo ========================================================
echo.
echo Launching Turbo Application...
python main_turbo.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo An error occurred while running the application.
    pause
)
