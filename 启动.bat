@echo off
chcp 65001 >nul
cd /d "%~dp0"

where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "tools\gui.py"
    exit /b
)

where python >nul 2>nul
if %errorlevel%==0 (
    python "tools\gui.py"
    pause
    exit /b
)

echo 没有找到 Python，请先安装 Python 3.11 以上版本。
pause
