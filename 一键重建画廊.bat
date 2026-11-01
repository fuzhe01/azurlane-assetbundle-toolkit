@echo off
chcp 65001 >nul 2>&1
title 一键重建画廊（新设备 / 换机器用）
setlocal
set "SCRIPT=%~dp0scripts\bootstrap_rebuild.py"

where py >nul 2>nul
if not errorlevel 1 (
    set "PY=py -3"
    goto run
)
where python >nul 2>nul
if not errorlevel 1 (
    set "PY=python"
    goto run
)
echo [错误] 没找到 py 或 python，请先安装 Python 3.11+ 并加入 PATH。
pause
exit /b 1

:run
%PY% "%SCRIPT%" %*
set "RC=%ERRORLEVEL%"
echo.
if "%~1"=="" pause
exit /b %RC%
