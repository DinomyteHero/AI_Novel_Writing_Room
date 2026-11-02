@echo off
rem Double-click to start the Writers Room on Windows.
rem The first run sets up a private copy of what the app needs in .venv, so
rem nothing is installed into your system Python. Later runs start straight away.
rem Anything after the name goes to the app, such as --port 9000.

setlocal
title Writers Room
cd /d "%~dp0"

if not exist "scripts\app.py" goto not_unzipped

set "VENV_PY=.venv\Scripts\python.exe"

rem A .venv copied from another computer or left by a removed Python won't run.
if exist "%VENV_PY%" "%VENV_PY%" -c "" >nul 2>&1 && goto install
if exist ".venv" rmdir /s /q ".venv"

set "PY="
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1 && set "PY=python"
if not defined PY goto no_python

echo Setting up the Writers Room. This happens once and takes a minute or two.
%PY% -m venv .venv
if errorlevel 1 goto setup_failed

:install
fc /b "requirements.txt" ".venv\installed-requirements.txt" >nul 2>&1 && goto run
echo Installing what the app needs...
"%VENV_PY%" -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto setup_failed
copy /y "requirements.txt" ".venv\installed-requirements.txt" >nul

:run
"%VENV_PY%" scripts\app.py %*
if errorlevel 1 goto stopped
exit /b 0

:not_unzipped
echo This file can't run from inside the ZIP.
echo Right-click the ZIP, choose Extract All, then double-click this file in the
echo folder that creates.
goto stopped

:no_python
echo The Writers Room needs Python 3.10 or newer, and this computer doesn't have it yet.
echo Opening the download page. Install Python, then double-click this file again.
start "" "https://www.python.org/downloads/"
goto stopped

:setup_failed
echo.
echo Setup didn't finish; see the message above. It usually means the internet
echo connection dropped. Double-click this file to try again.
goto stopped

:stopped
echo.
pause
exit /b 1
