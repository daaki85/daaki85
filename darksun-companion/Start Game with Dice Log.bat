@echo off
rem Starts Dark Sun with the dice log helper loaded, then opens Templar's Ledger.
cd /d "%~dp0"
call "%~dp0dscompanion\find-python.bat"
if errorlevel 1 exit /b 1
%PY% -m dscompanion launch
if errorlevel 1 pause
