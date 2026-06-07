@echo off
setlocal

cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel%==0 (
    python -m arxiv_translate %*
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        py -3 -m arxiv_translate %*
    ) else (
        echo Python was not found. Please install Python 3.10+ or add it to PATH.
        echo.
        pause
        exit /b 1
    )
)

set exit_code=%errorlevel%
echo.
if not "%exit_code%"=="0" echo arxiv_translate exited with code %exit_code%.
echo Window can be closed now.
pause
exit /b %exit_code%
