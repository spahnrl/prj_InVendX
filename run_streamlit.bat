@echo off
setlocal
title InVendX — Streamlit
cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
  call ".venv\Scripts\activate.bat"
) else if exist "venv\Scripts\activate.bat" (
  call "venv\Scripts\activate.bat"
)

where python >nul 2>&1
if errorlevel 1 (
  echo Python not found on PATH. Install Python 3.11+ or use py launcher.
  py -3 -m streamlit run operator_app.py
) else (
  python -m streamlit run operator_app.py
)

echo.
echo Streamlit exited. Press any key to close this window.
pause >nul
