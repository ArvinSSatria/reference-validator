@echo off
:: Request Administrator privileges
>nul 2>&1 "%SYSTEMROOT%\system32\cacls.exe" "%SYSTEMROOT%\system32\config\system"

if '%errorlevel%' NEQ '0' (
    echo Requesting administrative privileges...
    goto UACPrompt
) else ( goto gotAdmin )

:UACPrompt
    echo Set UAC = CreateObject^("Shell.Application"^) > "%temp%\getadmin.vbs"
    echo UAC.ShellExecute "%~s0", "", "", "runas", 1 >> "%temp%\getadmin.vbs"
    "%temp%\getadmin.vbs"
    exit /B

:gotAdmin
    if exist "%temp%\getadmin.vbs" ( del "%temp%\getadmin.vbs" )
    pushd "%CD%"
    CD /D "%~dp0"

:main
    echo ========================================
    echo   Reference Validator - Build Installer
    echo ========================================
    echo.
    echo Running as Administrator...
    echo.
    
    :: Set environment variables
    set CSC_IDENTITY_AUTO_DISCOVERY=false
    
    :: Clear cache
    echo Clearing electron-builder cache...
    if exist "%LOCALAPPDATA%\electron-builder\Cache" (
        rmdir /s /q "%LOCALAPPDATA%\electron-builder\Cache"
    )
    echo Cache cleared.
    echo.
    
    :: Build
    echo Starting build process...
    echo This may take 5-10 minutes...
    echo.
    
    call npm run build
    
    if %errorlevel% EQU 0 (
        echo.
        echo ========================================
        echo   BUILD SUCCESSFUL!
        echo ========================================
        echo.
        echo Output location: %~dp0dist
        echo.
        dir /b "%~dp0dist\*.exe" 2>nul
        echo.
    ) else (
        echo.
        echo ========================================
        echo   BUILD FAILED
        echo ========================================
        echo.
        echo Check error messages above.
        echo.
    )
    
    echo Press any key to exit...
    pause >nul
