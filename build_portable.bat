@echo off
REM Build LyPlex portable distribution
REM Requires: pip install pyinstaller
REM Requires: lilypond on PATH (not bundled)

setlocal
set ROOT=%~dp0
set OUT=%ROOT%portable

echo [1/3] Running PyInstaller...
"C:\Program Files\Python313\python.exe" -m PyInstaller --noconfirm lyplex.spec
if errorlevel 1 (
    echo PyInstaller failed.
    exit /b 1
)

echo [2/3] Assembling portable folder...
if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%"

REM Copy PyInstaller onedir output
xcopy /e /i /q "%ROOT%dist\LyPlex\*" "%OUT%\"

REM Copy bundled binaries
xcopy /e /i /q "%ROOT%bin\*" "%OUT%\bin\"

REM Copy soundfont
mkdir "%OUT%\soundfonts"
copy /y "%ROOT%soundfonts\GeneralUser-GS.sf2" "%OUT%\soundfonts\"

echo [3/3] Done.
echo.
echo Portable folder: %OUT%
echo NOTE: LilyPond must be installed and on PATH separately.
echo       Get it from https://lilypond.org/download.html
endlocal
