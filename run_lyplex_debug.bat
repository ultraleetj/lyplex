@echo off
cd /d "%~dp0"
python lyplex_gui.py
echo.
echo Exit code: %errorlevel%
pause
