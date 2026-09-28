@echo off
rem Starts Dark Sun with the dice log helper loaded, then opens the companion.
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python was not found. Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" on the first installer screen.
  pause
  exit /b 1
)
%PY% -m dscompanion launch
if errorlevel 1 pause
