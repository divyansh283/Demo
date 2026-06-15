@echo off
setlocal
cd /d "%~dp0"

echo Starting OCR Utility...

if not exist "OCR_Input" mkdir "OCR_Input"
if not exist "OCR_Output" mkdir "OCR_Output"

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
    ".venv\Scripts\python.exe" src\main.py
) else (
    echo WARNING: .venv was not found. Using system Python.
    echo Run Install_Dependencies.bat first if the app does not start.
    python src\main.py
)

pause
