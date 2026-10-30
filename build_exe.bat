@echo off
chcp 65001 >nul
REM ============================================================
REM  AeroForge — самостоятелен EXE (PyInstaller, само Windows)
REM
REM  Резултат: dist\AeroForge\AeroForge.exe
REM  Използва .venv, ако съществува (иначе системния Python).
REM ============================================================
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" -c "import sys" >nul 2>&1
if errorlevel 1 (
    echo [ГРЕШКА] Python не е намерен. Пусни първо start.bat.
    pause
    exit /b 1
)

echo Инсталирам PyInstaller (ако липсва) ...
"%PY%" -m pip install --disable-pip-version-check --upgrade pyinstaller >nul
if errorlevel 1 (
    echo [ГРЕШКА] PyInstaller не може да се инсталира.
    pause
    exit /b 1
)

echo Чистене на стария build ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo Сглобяване ...
"%PY%" -m PyInstaller AeroForge.spec --noconfirm
if errorlevel 1 (
    echo [ГРЕШКА] Сглобяването се провали.
    pause
    exit /b 1
)

echo.
echo Готово: dist\AeroForge\AeroForge.exe
pause

endlocal
