@echo off
echo ========================================
echo Building Complete Installer
echo ========================================

REM Clean old build folders first
echo.
echo Step 0: Cleaning old build folders...
if exist "dist" rmdir /S /Q "dist"
if exist "flask_server" rmdir /S /Q "flask_server"
if exist "..\dist" rmdir /S /Q "..\dist"
if exist "..\build" rmdir /S /Q "..\build"
echo Old build folders cleaned

REM Copy .env first before build
echo.
echo Step 1: Copying .env to Flask server...
copy /Y "..\\.env" "flask_server\\.env"
if errorlevel 1 (
    echo Warning: .env file not found or copy failed
) else (
    echo .env copied successfully
)

REM Build Electron app
echo.
echo Step 2: Building Electron app...
call npm run build
if errorlevel 1 (
    echo BUILD FAILED!
    pause
    exit /b 1
)

REM Copy flask_server to resources manually
echo.
echo Step 3: Copying Flask server to resources...
xcopy /E /I /Y /H "flask_server" "dist\win-unpacked\resources\flask_server"

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
