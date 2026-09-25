@echo off
title PBI Indexer - Offline Consolidation and Mapping Tool
cd /d "%~dp0"
python main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo An error occurred while launching the tool.
    pause
)
