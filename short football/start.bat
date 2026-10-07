@echo off
rem Double-click this, or run it from PowerShell as  .\start.bat
rem
rem It exists because the per-round command is long, and a long command pasted
rem into PowerShell is where the quoting goes wrong. Edit the four settings
rem below once; after that this file is the only thing you ever run.

setlocal
cd /d "%~dp0"

set BANKROLL=21000
set BASE=200
set STAGES=5
set STOPLOSS=19800

rem The py launcher is the reliable way to reach Python on Windows; plain
rem "python" can open the Microsoft Store instead of running anything.
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

if not exist "data\sokaligi_state.json" (
  echo Setting up a new ladder...
  %PY% sokaligi_bot.py init --bankroll %BANKROLL% --base %BASE% --stages %STAGES% --step 100 --books soka-1 soka-2 soka-3 --feed shared --stop-loss %STOPLOSS%
  if not %errorlevel%==0 goto fail
  echo.
)

%PY% sokaligi_bot.py run
if not %errorlevel%==0 goto fail
pause
exit /b 0

:fail
echo.
echo Something went wrong - the message above says what.
pause
exit /b 1
