@echo off
chcp 65001 >nul
title Azur Lane Asset Update Console (local server on 8788)
set "SCRIPT=%~dp0scripts\pipeline_panel.py"

rem Prefer launcher 'py'; fall back to 'python' if not on PATH.
rem ASCII-only on purpose: cmd parses .bat bytes with the OEM codepage,
rem so non-ASCII text can break the command splitting.
where py >nul 2>nul
if not errorlevel 1 (
  py "%SCRIPT%" %*
  goto end
)
where python >nul 2>nul
if not errorlevel 1 (
  python "%SCRIPT%" %*
  goto end
)
echo [ERROR] py / python not found. Install Python and add it to PATH.

:end
rem Keep the window open on error so the message stays visible.
pause
