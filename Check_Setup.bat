@echo off
setlocal
cd /d "%~dp0"

echo ====================================================
echo RCB OCR Utility - Windows Setup Check
echo ====================================================
echo Project folder:
echo   %CD%
echo.

echo [1] Python
where python >nul 2>nul
if errorlevel 1 (
    echo FAIL: python was not found in PATH.
) else (
    python --version
)
echo.

echo [2] Virtual environment
if exist ".venv\Scripts\python.exe" (
    echo PASS: .venv found.
) else (
    echo WARN: .venv not found. Run Install_Dependencies.bat.
)
echo.

echo [3] Tesseract executable
if defined TESSERACT_CMD (
    echo TESSERACT_CMD is set to:
    echo   %TESSERACT_CMD%
)
if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
    echo PASS: Tesseract found at C:\Program Files\Tesseract-OCR\tesseract.exe
) else if exist "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe" (
    echo PASS: Tesseract found at C:\Program Files (x86)\Tesseract-OCR\tesseract.exe
) else if defined TESSERACT_CMD (
    if exist "%TESSERACT_CMD%" (
        echo PASS: Tesseract found from TESSERACT_CMD.
    ) else (
        echo FAIL: TESSERACT_CMD path does not exist.
    )
) else (
    echo FAIL: Tesseract was not found.
)
echo.

echo [4] Project tessdata
if exist "tessdata\eng.traineddata" (echo PASS: eng.traineddata) else (echo FAIL: tessdata\eng.traineddata missing)
if exist "tessdata\hin.traineddata" (echo PASS: hin.traineddata) else (echo FAIL: tessdata\hin.traineddata missing)
if exist "tessdata\mar.traineddata" (echo PASS: mar.traineddata) else (echo FAIL: tessdata\mar.traineddata missing)
if exist "tessdata\guj.traineddata" (echo PASS: guj.traineddata) else (echo FAIL: tessdata\guj.traineddata missing)
if exist "tessdata\osd.traineddata" (echo PASS: osd.traineddata) else (echo FAIL: tessdata\osd.traineddata missing)
echo.

echo [5] Required project files
if exist "src\main.py" (echo PASS: src\main.py) else (echo FAIL: src\main.py missing)
if exist "config.ini" (echo PASS: config.ini) else (echo FAIL: config.ini missing)
if exist "requirements.txt" (echo PASS: requirements.txt) else (echo FAIL: requirements.txt missing)
if exist "FreeSans.ttf" (echo PASS: FreeSans.ttf) else (echo WARN: FreeSans.ttf missing)
echo.

echo [6] Input/output folders
if exist "OCR_Input" (echo PASS: OCR_Input) else (echo WARN: OCR_Input missing; Run_OCR_Utility.bat will create it)
if exist "OCR_Output" (echo PASS: OCR_Output) else (echo WARN: OCR_Output missing; Run_OCR_Utility.bat will create it)
echo.

echo ====================================================
echo Check complete.
echo ====================================================
pause
