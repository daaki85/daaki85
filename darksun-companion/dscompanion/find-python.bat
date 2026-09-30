@echo off
rem Used by the .bat files next to the dscompanion folder: finds a 64-bit Python 3.8 or
rem later with tkinter and, if there is none, offers to install the official one from
rem python.org through Windows' own package manager (winget). Sets PY (runs with a console)
rem and PYW (runs without one). Exit code 1: no Python.
set "PY="
set "PYW="
call :find
if defined PY exit /b 0
echo.
echo Templar's Ledger needs Python (free, from python.org), and it isn't installed.
where winget >nul 2>nul
if errorlevel 1 goto :manual
choice /c YN /m "Install it now with Windows' package manager (winget)"
if errorlevel 2 goto :manual
winget install --exact --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
call :find
if defined PY exit /b 0
echo.
echo Python is installed, but this window doesn't know yet.
echo Close it and start the .bat file again.
pause
exit /b 1

:manual
echo.
echo Install it from https://www.python.org/downloads/ (the 64-bit Windows installer),
echo tick "Add python.exe to PATH" on its first screen, then start this again.
pause
exit /b 1

:find
call :try py -3-64
if not errorlevel 1 (set "PYW=pyw -3-64" & exit /b 0)
call :try python
if not errorlevel 1 (set "PYW=pythonw" & exit /b 0)
rem just installed by winget for this user, before this window's PATH knows about it
set "USERPY=%LOCALAPPDATA%\Programs\Python\Python312"
if not exist "%USERPY%\python.exe" exit /b 1
call :try "%USERPY%\python.exe"
if errorlevel 1 exit /b 1
set PYW="%USERPY%\pythonw.exe"
exit /b 0

:try
rem (Windows' "python" that only opens the Store fails this too)
set "PY="
%* -c "import sys, struct, tkinter; sys.exit(sys.version_info < (3, 8) or struct.calcsize('P') != 8)" >nul 2>nul
if errorlevel 1 exit /b 1
set PY=%*
exit /b 0
