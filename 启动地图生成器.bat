@echo off
setlocal
cd /d "%~dp0"

rem Locate a Python interpreter (prefer the managed one bundled with WorkBuddy).
set "PY="
if exist "%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe" (
  set "PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
)
if not defined PY (
  for %%P in ("%USERPROFILE%\.workbuddy\binaries\python\versions\*\python.exe") do (
    if not defined PY set "PY=%%~fP"
  )
)
if not defined PY (
  where py >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo [ERROR] Python 3 not found. Please install it first.
  pause
  exit /b 1
)

echo Using Python: %PY%
echo Starting random map generator UI ...
%PY% "%~dp0tools\gui_server.py" %*
if errorlevel 1 pause
