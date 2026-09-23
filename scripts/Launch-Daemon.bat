@echo off
setlocal
cd /d "%~dp0.."

echo ========================================================
echo   Antigravity Auto-Pilot Headless Daemon Launcher
echo ========================================================
echo Running 24/7 background monitor for quota limits & auto-swap...
echo.

:: 1. Check python in PATH
where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    python "main.py" --daemon
    exit /b 0
)

:: 2. Check py launcher
where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
    py -3 "main.py" --daemon
    exit /b 0
)

:: 3. Check common Python locations
if exist "%USERPROFILE%\anaconda3\python.exe" (
    "%USERPROFILE%\anaconda3\python.exe" "main.py" --daemon
    exit /b 0
)
if exist "%USERPROFILE%\miniconda3\python.exe" (
    "%USERPROFILE%\miniconda3\python.exe" "main.py" --daemon
    exit /b 0
)
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" "main.py" --daemon
    exit /b 0
)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "main.py" --daemon
    exit /b 0
)
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" "main.py" --daemon
    exit /b 0
)

echo [ERROR] Python tidak ditemukan di sistem Anda!
echo Silakan install Python 3.10+ dari https://www.python.org atau Anaconda.
pause
exit /b 1
