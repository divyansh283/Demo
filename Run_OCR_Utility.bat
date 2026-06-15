@echo off
setlocal
cd /d "%~dp0"

echo Starting OCR Utility...

if not exist "OCR_Input" mkdir "OCR_Input"
if not exist "OCR_Output" mkdir "OCR_Output"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" src\main.py
) else (
    echo WARNING: .venv was not found. Using system Python.
    echo Run Install_Dependencies.bat first if the app does not start.
    python src\main.py
)

pause
