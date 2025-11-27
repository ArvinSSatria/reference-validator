@echo off
echo ========================================
echo Building Complete Installer
echo ========================================

REM Build Electron app first
echo.
echo Step 1: Building Electron app...
call npm run build
if errorlevel 1 (
    echo BUILD FAILED!
    pause
    exit /b 1
)

REM Copy flask_server to resources manually
echo.
echo Step 2: Copying Flask server to resources...
xcopy /E /I /Y "flask_server" "dist\win-unpacked\resources\flask_server"

if errorlevel 1 (
    echo Failed to copy Flask server!
    pause
    exit /b 1
)

echo.
echo ========================================
echo BUILD COMPLETE!
echo ========================================
echo.
echo Installer: dist\Reference Validator 1.0.0.exe
echo Unpacked: dist\win-unpacked\
echo.
echo Flask server has been manually added to resources folder.
echo You can test the unpacked version before distributing.
echo.
pause
