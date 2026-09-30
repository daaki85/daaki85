@echo off
rem Starts Dark Sun with the in-game rolls, THAC0, saves, thief skills and spell slots,
rem and no Templar's Ledger window (the dice log runs unseen until the game closes).
cd /d "%~dp0"
call "%~dp0dscompanion\find-python.bat"
if errorlevel 1 exit /b 1
start "" %PYW% -m dscompanion play
