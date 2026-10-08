@echo off
setlocal
where python >nul 2>nul
if errorlevel 1 (py -3 "%~dp0claude_history.py" --open %*) else (python "%~dp0claude_history.py" --open %*)
if errorlevel 1 pause
