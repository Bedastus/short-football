@echo off
rem Opens one browser window per SokaBet account, tiled left to right.
rem Run this once at the start of a session, before start.bat.
rem
rem Window 1 = soka-1 = slip A, window 2 = soka-2 = slip B, window 3 = soka-3
rem = slip C. That order is the only thing tying an account to a ticket, so
rem keep the windows where they open.

setlocal
cd /d "%~dp0"

set ACCOUNTS=3

set PY=python
where py >nul 2>nul
if %errorlevel%==0 set PY=py -3

%PY% --version >nul 2>nul
if not %errorlevel%==0 (
  echo.
  echo Python was not found. Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during setup.
  echo.
  pause
  exit /b 1
)

%PY% open_books.py --accounts %ACCOUNTS%
if not %errorlevel%==0 (
  echo.
  echo Could not open the browsers - the message above says why.
  echo If no browser was found, pass one explicitly, for example:
  echo    %PY% open_books.py --browser "C:\Program Files\Google\Chrome\Application\chrome.exe"
  echo.
)
pause
