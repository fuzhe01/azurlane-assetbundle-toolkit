@echo off
chcp 65001 >nul 2>&1
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
set "SCRIPT=%~dp0mumu_adb.py"

if not defined PY (
    echo [ERROR] Python not found: install Python 3.13+, or put py/python on PATH
    pause
    exit /b 1
)

if "%~1"=="" (
    %PY% "%SCRIPT%" info
) else (
    %PY% "%SCRIPT%" %*
)

echo.
pause
