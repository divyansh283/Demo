@echo off
setlocal
cd /d "%~dp0"

echo Starting OCR Utility...

echo Note: The GUI can be opened without existing OCR_Input / OCR_Output folders.
echo You can select existing folders from the app before processing.

echo.
if not exist "tessdata\eng.traineddata" (
    echo.
    echo ERROR: Tesseract language data is missing.
    echo Expected file:
    echo   %CD%\tessdata\eng.traineddata
    echo.
    echo Fix:
    echo   Copy the full tessdata folder into this project folder.
    echo   The folder must contain eng.traineddata, hin.traineddata, mar.traineddata, guj.traineddata, and osd.traineddata.
    echo.
    pause
    exit /b 1
)

if not exist "tessdata\hin.traineddata" echo WARNING: tessdata\hin.traineddata is missing. Hindi OCR may fail.
if not exist "tessdata\mar.traineddata" echo WARNING: tessdata\mar.traineddata is missing. Marathi OCR may fail.
if not exist "tessdata\guj.traineddata" echo WARNING: tessdata\guj.traineddata is missing. Gujarati OCR may fail.
if not exist "tessdata\osd.traineddata" echo WARNING: tessdata\osd.traineddata is missing. Orientation detection may fail.

set "TESSDATA_PREFIX=%CD%\tessdata"

if not defined TESSERACT_CMD (
    if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" set "TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe"
)
if not defined TESSERACT_CMD (
    if exist "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe" set "TESSERACT_CMD=C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
)

if not defined TESSERACT_CMD (
    echo.
    echo ERROR: Tesseract OCR is not installed or was not found.
    echo Install it at:
    echo   C:\Program Files\Tesseract-OCR\tesseract.exe
    echo.
    echo If it is installed somewhere else, set TESSERACT_CMD to the full tesseract.exe path.
    echo.
    pause
    exit /b 1
)

if exist ".venv\Scripts\python.exe" (
    set "PYTHONPATH=%CD%"
    set "TESSDATA_PREFIX=%CD%\tessdata"
    ".venv\Scripts\python.exe" src\main.py
    if errorlevel 1 (
        echo.
        echo ERROR: OCR application failed to start.
        echo Check the error message above.
        pause
        exit /b 1
    )
) else (
    echo.
    echo ERROR: Virtual environment not found at .venv\Scripts\python.exe
    echo Please run Install_Dependencies.bat first.
    echo.
    pause
    exit /b 1
)
