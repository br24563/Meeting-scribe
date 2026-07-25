@echo off
title EchoPad Launcher
cd /d "%~dp0"

echo ============================================
echo   EchoPad - Starting up...
echo ============================================
echo.

where docker >nul 2>nul
if errorlevel 1 (
    echo Docker Desktop was not found on this computer.
    echo Please install it from https://www.docker.com/products/docker-desktop/
    echo then double-click this file again.
    echo.
    pause
    exit /b 1
)

docker compose up -d --build
if errorlevel 1 (
    echo.
    echo Something went wrong starting EchoPad.
    echo Make sure Docker Desktop is open and running, then try again.
    echo.
    pause
    exit /b 1
)

echo.
echo Waiting for EchoPad to finish setting up...
echo (First run downloads the AI model - this can take a few minutes.
echo  Later runs will be much faster.)
echo.

:waitloop
curl -s -o nul -w "%%{http_code}" http://localhost:8501 > "%TEMP%\echopad_status.txt" 2>nul
set /p STATUS=<"%TEMP%\echopad_status.txt"
if "%STATUS%"=="200" goto ready
timeout /t 3 >nul
goto waitloop

:ready
echo EchoPad is ready! Opening in your browser...
start http://localhost:8501

echo.
echo You can close this window, or leave it open to watch EchoPad's logs.
echo To stop EchoPad later, run "docker compose down" from this folder.
pause
