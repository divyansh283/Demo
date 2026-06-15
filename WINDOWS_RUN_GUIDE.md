# RCB OCR Utility - Windows Run Guide

This guide explains how to zip, copy, install, run, and troubleshoot the OCR
utility on a Windows system.

## 1. What This App Does

The app processes a full input folder. It reads all supported files from the
selected input folder, including files inside subfolders, and saves OCR output
to the selected output folder.

Supported input files:

```text
.pdf
.jpg
.jpeg
.png
.tiff
.tif
.heic
```

Outputs:

```text
*_text.txt
*_tables.csv
*_payload.xml
*_human_report.pdf
exceptions.json
Quarantine\...
```

## 2. Your Current Error

Error shown:

```text
Error opening data file ...\tessdata/eng.traineddata
Failed loading language 'eng'
Tesseract couldn't load any languages!
Could not initialize tesseract.
```

Meaning:

Tesseract is installed or callable, but it cannot find the language data file
`eng.traineddata`.

This usually happens when:

- The `tessdata` folder was not included in the zip.
- The zip was extracted incorrectly and files are in the wrong folder.
- Tesseract was installed without language data.
- `eng.traineddata`, `hin.traineddata`, `mar.traineddata`, `guj.traineddata`,
  or `osd.traineddata` are missing.

Expected project structure:

```text
RCB_Utility
  Install_Dependencies.bat
  Run_OCR_Utility.bat
  config.ini
  requirements.txt
  FreeSans.ttf
  src
  tessdata
    eng.traineddata
    hin.traineddata
    mar.traineddata
    guj.traineddata
    osd.traineddata
```

Fix:

1. Check that this folder exists:

```text
RCB_Utility\tessdata
```

2. Check that this file exists:

```text
RCB_Utility\tessdata\eng.traineddata
```

3. If it is missing, copy the full `tessdata` folder from the original project
   into the extracted `RCB_Utility` folder.

4. Also install Tesseract OCR at:

```text
C:\Program Files\Tesseract-OCR\tesseract.exe
```

The app now checks both:

```text
RCB_Utility\tessdata
C:\Program Files\Tesseract-OCR\tessdata
```

## 3. How To Create The Zip

On Linux, run this from the parent folder:

```bash
cd /home/admin1/Divyansh/RCB_Utility-20260615T061304Z-3-001
zip -r RCB_Utility_Windows.zip RCB_Utility \
  -x "RCB_Utility/.git/*" \
  -x "RCB_Utility/.venv/*" \
  -x "RCB_Utility/__pycache__/*" \
  -x "RCB_Utility/*/__pycache__/*" \
  -x "RCB_Utility/*/*/__pycache__/*" \
  -x "RCB_Utility/*.pyc" \
  -x "RCB_Utility/OCR_Input/*" \
  -x "RCB_Utility/OCR_Output/*"
```

Before sending the zip, confirm it contains:

```text
RCB_Utility\tessdata\eng.traineddata
RCB_Utility\src\main.py
RCB_Utility\Run_OCR_Utility.bat
RCB_Utility\Install_Dependencies.bat
RCB_Utility\Check_Setup.bat
```

## 4. Windows System Setup

Install these once:

1. Python 3.10 or 3.11

Download from:

```text
https://www.python.org/downloads/
```

Important: tick this during install:

```text
Add python.exe to PATH
```

2. Tesseract OCR

Install Tesseract OCR for Windows. Recommended install path:

```text
C:\Program Files\Tesseract-OCR\tesseract.exe
```

3. Extract the project zip to a simple path:

```text
C:\work\RCB_Utility
```

Avoid paths with too many nested folders or special characters.

## 5. First Run

Open the extracted folder and double-click:

```text
Install_Dependencies.bat
```

This creates:

```text
.venv
OCR_Input
OCR_Output
```

Then double-click:

```text
Run_OCR_Utility.bat
```

If there is any error, double-click:

```text
Check_Setup.bat
```

It checks Python, Tesseract, `tessdata`, required project files, and folders.

## 6. How To Use The App

1. Select `INPUT DIRECTORY`.
2. Select `OUTPUT DIRECTORY`.
3. Put PDFs/images in the input folder.
4. Click `LAUNCH PROCESSING`.

The app processes all supported files in the selected input folder and its
subfolders.

## 7. Azure Configuration

The project currently has Azure endpoint and API key in `config.ini`.

Keep the zip private because `config.ini` contains a real key.

If Azure fails, check:

- Internet connection.
- Azure endpoint.
- Azure API key.
- Azure Document Intelligence resource status.

## 8. Common Errors And Fixes

### `python is not recognized`

Cause:

Python is not installed or PATH was not enabled.

Fix:

Reinstall Python and tick:

```text
Add python.exe to PATH
```

### `No module named customtkinter` or `No module named fitz`

Cause:

Dependencies were not installed.

Fix:

Double-click:

```text
Install_Dependencies.bat
```

### `TesseractNotFoundError`

Cause:

Tesseract OCR is not installed or not at the default path.

Fix:

Install Tesseract at:

```text
C:\Program Files\Tesseract-OCR\tesseract.exe
```

If installed elsewhere, set an environment variable:

```bat
setx TESSERACT_CMD "D:\YourPath\tesseract.exe"
```

Restart Command Prompt/app after setting it.

### `Failed loading language 'eng'`

Cause:

`eng.traineddata` is missing.

Fix:

Make sure this file exists:

```text
RCB_Utility\tessdata\eng.traineddata
```

Also check:

```text
C:\Program Files\Tesseract-OCR\tessdata\eng.traineddata
```

### `Failed loading language 'hin'`, `'mar'`, or `'guj'`

Cause:

Hindi, Marathi, or Gujarati traineddata file is missing.

Fix:

Make sure these files exist:

```text
RCB_Utility\tessdata\hin.traineddata
RCB_Utility\tessdata\mar.traineddata
RCB_Utility\tessdata\guj.traineddata
```

### `Azure credentials are missing`

Cause:

Azure endpoint/key are blank.

Fix:

Fill `[AZURE]` in `config.ini`.

### Azure API error

Cause:

Bad key, expired key, wrong endpoint, no internet, or Azure service issue.

Fix:

Verify Azure Document Intelligence key and endpoint in Azure Portal.

### `Input directory missing`

Cause:

Selected input folder does not exist.

Fix:

Select a valid folder from the GUI.

### App finishes immediately with no files processed

Cause:

Input folder has no supported files.

Fix:

Add PDF/JPG/PNG/TIFF/HEIC files to the input folder.

## 9. Final Checklist Before Sending Zip

Confirm these exist:

```text
Check_Setup.bat
Run_OCR_Utility.bat
Install_Dependencies.bat
requirements.txt
config.ini
FreeSans.ttf
src
tessdata
tessdata\eng.traineddata
tessdata\hin.traineddata
tessdata\mar.traineddata
tessdata\guj.traineddata
tessdata\osd.traineddata
```

Do not include:

```text
.git
.venv
__pycache__
*.pyc
OCR_Input
OCR_Output
```
