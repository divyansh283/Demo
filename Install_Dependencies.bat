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

echo.
echo Running local OCR pre-flight checks...

if not exist "tessdata\eng.traineddata" (
    echo WARNING: tessdata\eng.traineddata is missing.
    echo Copy the full tessdata folder into this project before running OCR.
)
if not exist "tessdata\hin.traineddata" echo WARNING: tessdata\hin.traineddata is missing.
if not exist "tessdata\mar.traineddata" echo WARNING: tessdata\mar.traineddata is missing.
if not exist "tessdata\guj.traineddata" echo WARNING: tessdata\guj.traineddata is missing.
if not exist "tessdata\osd.traineddata" echo WARNING: tessdata\osd.traineddata is missing.

if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
    echo Tesseract found at C:\Program Files\Tesseract-OCR\tesseract.exe
) else if exist "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe" (
    echo Tesseract found at C:\Program Files (x86)\Tesseract-OCR\tesseract.exe
) else (
    echo WARNING: Tesseract OCR was not found at the default Windows install path.
    echo Install Tesseract before running OCR.
)

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
