@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (py -3 -m sessiontool %*) else (python -m sessiontool %*)
if errorlevel 1 pause
