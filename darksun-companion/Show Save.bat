@echo off
rem Drag a SAVEnn.SAV file onto this file to see the party stored in it.
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
if "%~1"=="" (
  echo Drag a save file such as SAVE01.SAV onto "Show Save.bat" to see its party.
  pause
  exit /b 1
)
%PY% -m dscompanion save "%~1"
pause
