@echo off
setlocal
cd /d "%~dp0"

echo ===================================================
echo   Antigravity Control Center - Shortcut Installer
echo ===================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$sh = New-Object -ComObject WScript.Shell; " ^
    "$desktop = [Environment]::GetFolderPath('Desktop'); " ^
    "$shortcut = $sh.CreateShortcut(\"$desktop\Antigravity Control Center.lnk\"); " ^
    "$shortcut.TargetPath = \"%~dp0Launch-GUI.bat\"; " ^
    "$shortcut.Arguments = ''; " ^
    "$shortcut.WorkingDirectory = (Resolve-Path '%~dp0..').Path; " ^
    "$ico = (Resolve-Path '%~dp0..\assets\icons\app_icon.ico').Path; " ^
    "$shortcut.IconLocation = \"$ico,0\"; " ^
    "$shortcut.Description = 'Antigravity Multi-Account Controller'; " ^
    "$shortcut.WindowStyle = 7; " ^
    "$shortcut.Save(); " ^
    "Write-Host '[SUCCESS] Shortcut created on Desktop!' -ForegroundColor Green; " ^
    "Write-Host 'You can now double-click \"Antigravity Control Center\" on your Desktop.' -ForegroundColor Cyan"

echo.
pause
