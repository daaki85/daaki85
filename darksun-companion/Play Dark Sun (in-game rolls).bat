@echo off
rem Starts Dark Sun with the in-game rolls, THAC0, saves, thief skills and spell slots,
rem and no Templar's Ledger window (the dice log runs unseen until the game closes).
cd /d "%~dp0"
set "PY="
where pyw >nul 2>nul && set "PY=pyw -3"
if not defined PY where pythonw >nul 2>nul && set "PY=pythonw"
if not defined PY (
  echo Python was not found. Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" on the first installer screen.
  pause
  exit /b 1
)
start "" %PY% -m dscompanion play
