@echo off
setlocal
set "DI_PYTHONW="
if exist "%~dp0.venv\Scripts\pythonw.exe" set "DI_PYTHONW=%~dp0.venv\Scripts\pythonw.exe"
if not defined DI_PYTHONW if exist "%ProgramData%\anaconda3\pythonw.exe" set "DI_PYTHONW=%ProgramData%\anaconda3\pythonw.exe"
if not defined DI_PYTHONW if exist "%USERPROFILE%\anaconda3\pythonw.exe" set "DI_PYTHONW=%USERPROFILE%\anaconda3\pythonw.exe"
if not defined DI_PYTHONW for /f "delims=" %%P in ('where pythonw.exe 2^>nul') do if not defined DI_PYTHONW set "DI_PYTHONW=%%P"
if not defined DI_PYTHONW (
    echo Python 3 with Tkinter was not found.
    echo Run: python tools\desktop_viewer.py --latest
    pause
    exit /b 1
)
start "DiskInventory Desktop" "%DI_PYTHONW%" "%~dp0tools\desktop_viewer.py" --latest
endlocal
