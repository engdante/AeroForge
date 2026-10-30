@echo off
chcp 65001 >nul
REM ============================================================
REM  AeroForge — стартиране под Windows
REM
REM  Какво прави:
REM    1) намира Python 3.10+ (python или py -3);
REM    2) създава локална среда .venv (ако още я няма);
REM    3) инсталира зависимостите от app\requirements.txt
REM       (само ако eel липсва в средата);
REM    4) стартира приложението (Eel + браузър).
REM
REM  Аргументи:  start.bat [порт]
REM  Пример:     start.bat 8080
REM ============================================================
setlocal
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

REM ---------- 1. Python ----------
set "SYSTEM_PY="
where python >nul 2>&1 && set "SYSTEM_PY=python"
if not defined SYSTEM_PY (
    where py >nul 2>&1 && set "SYSTEM_PY=py -3"
)
if not defined SYSTEM_PY (
    echo [ГРЕШКА] Python не е намерен.
    echo.
    echo Инсталирай Python 3.10 или по-нов от https://www.python.org/downloads/
    echo ВАЖНО: при инсталацията сложи отметка "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

%SYSTEM_PY% -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3,10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ГРЕШКА] Намереният Python е по-стар от 3.10.
    echo Провери с:  %SYSTEM_PY% --version
    pause
    exit /b 1
)

REM ---------- 2. Локална среда .venv ----------
if not exist "%VENV_PY%" (
    echo Създавам локална среда .venv ...
    %SYSTEM_PY% -m venv "%~dp0.venv"
    if errorlevel 1 (
        echo [ГРЕШКА] Не мога да създам .venv.
        echo Провери дали Python е инсталиран с модул venv.
        pause
        exit /b 1
    )
)

REM ---------- 3. Зависимости ----------
"%VENV_PY%" -c "import eel" >nul 2>&1
if errorlevel 1 (
    echo Инсталирам зависимости от app\requirements.txt ...
    "%VENV_PY%" -m pip install --disable-pip-version-check -r "%~dp0app\requirements.txt"
    if errorlevel 1 (
        echo [ГРЕШКА] Инсталацията на зависимостите се провали.
        echo Провери интернет връзката и опитай ръчно:
        echo   .venv\Scripts\python.exe -m pip install -r app\requirements.txt
        pause
        exit /b 1
    )
)

REM ---------- 4. Стартиране ----------
echo.
echo Стартиране на AeroForge ...  (затвори конзолата, за да спреш)
"%VENV_PY%" "%~dp0app\server.py" %*
if errorlevel 1 (
    echo.
    echo [ГРЕШКА] Приложението приключи с грешка — виж съобщението по-горе.
    pause
)

endlocal
