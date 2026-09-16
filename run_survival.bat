@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 survival.py
) else (
  python survival.py
)
endlocal
