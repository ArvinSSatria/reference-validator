@echo off
echo ========================================
echo Building Flask Server with PyInstaller
echo ========================================
echo.

REM Activate virtual environment
if exist .venv\Scripts\activate.bat (
    echo Activating virtual environment...
    call .venv\Scripts\activate.bat
) else (
    echo Error: Virtual environment not found!
    echo Please create virtual environment first: python -m venv .venv
    pause
    exit /b 1
)

REM Install PyInstaller if not already installed
echo.
echo Checking PyInstaller...
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

REM Clean previous builds
echo.
echo Cleaning previous builds...
if exist build rmdir /s /q build
if exist dist\flask_server rmdir /s /q dist\flask_server

REM Build with PyInstaller
echo.
echo Building Flask server executable...
pyinstaller build_flask.spec

if errorlevel 1 (
    echo.
    echo BUILD FAILED!
    pause
    exit /b 1
)

echo.
echo ========================================
echo BUILD SUCCESSFUL!
echo ========================================
echo Output: dist\flask_server\
echo.
pause
