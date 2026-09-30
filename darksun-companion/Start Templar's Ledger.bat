@echo off
rem Opens Templar's Ledger. Start the game in DOSBox first.
cd /d "%~dp0"
call "%~dp0dscompanion\find-python.bat"
if errorlevel 1 exit /b 1
%PY% -m dscompanion view
if errorlevel 1 pause
