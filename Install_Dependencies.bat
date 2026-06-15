@echo off
setlocal
cd /d "%~dp0"

echo ====================================================
echo Installing Python Dependencies for OCR Utility
echo ====================================================
echo.
echo This setup creates a local .venv folder and installs all Python packages.
echo Make sure Python 3.10 or 3.11 is installed with "Add python.exe to PATH".
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python was not found in PATH.
    echo Install Python from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Could not create virtual environment.
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo ERROR: Could not activate .venv.
    pause
    exit /b 1
)

echo Upgrading pip...
python -m pip install --upgrade pip
if errorlevel 1 goto install_failed

echo Installing required libraries...
python -m pip install -r requirements.txt
if errorlevel 1 goto install_failed

if not exist "OCR_Input" mkdir "OCR_Input"
if not exist "OCR_Output" mkdir "OCR_Output"

echo.
echo ====================================================
echo Installation Complete!
echo You can now use Run_OCR_Utility.bat to launch the app.
echo ====================================================
pause
exit /b 0

:install_failed
echo.
echo ERROR: Dependency installation failed.
echo Check your internet connection and run this BAT again.
pause
exit /b 1
