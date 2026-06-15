# RCB OCR Utility - Windows Setup Guide

RCB OCR Utility is a Windows desktop application for extracting text and tables
from scanned PDFs/images. It uses local Tesseract OCR first, then escalates to
Azure Document Intelligence for low-confidence pages or complex tables.

## What It Does

- Reads PDF, JPG, JPEG, PNG, TIFF, TIF, and HEIC files from an input folder.
- Extracts digital PDF text when the text layer is valid.
- Runs local OCR with English, Hindi, Marathi, and Gujarati language data.
- Removes stamp ink and grid lines before local OCR.
- Sends difficult table-heavy pages to Azure Document Intelligence when configured.
- Validates financial tables and reconciles totals.
- Routes unreconciled documents to `OCR_Output\Quarantine`.

## Windows Requirements

Install these once on the Windows machine:

1. Python 3.10 or 3.11
   - Download from https://www.python.org/downloads/
   - During install, tick `Add python.exe to PATH`.

2. Tesseract OCR for Windows
   - Recommended installer: UB Mannheim Tesseract OCR.
   - Install to the default path:
     `C:\Program Files\Tesseract-OCR\tesseract.exe`
   - The project already includes `tessdata` files for:
     `eng`, `hin`, `mar`, `guj`, and `osd`.

3. Internet access for first-time Python dependency installation.

## First-Time Setup

Extract the project zip to a simple path, for example:

```text
C:\work\RCB_Utility
```

Then double-click:

```text
Install_Dependencies.bat
```

This creates a local `.venv` folder, installs Python packages, and creates:

```text
OCR_Input
OCR_Output
```

## Running The App

Put documents into:

```text
OCR_Input
```

Then double-click:

```text
Run_OCR_Utility.bat
```

The GUI opens. You can use the default folders or select different folders from
the interface.

If anything fails, double-click:

```text
Check_Setup.bat
```

It checks Python, Tesseract, `tessdata`, and required project files.

## Azure Setup

Azure is optional for basic local OCR, but required for best table extraction.

Recommended Windows environment variables:

```bat
setx AZURE_DOCUMENT_ENDPOINT "https://your-resource.cognitiveservices.azure.com"
setx AZURE_DOCUMENT_KEY "your-api-key"
```

Close and reopen Command Prompt or restart Windows after `setx`.

Alternative: fill the `[AZURE]` section in `config.ini`. Avoid sharing a zip that
contains real Azure keys.

## Output Files

For each processed document, output files are written to `OCR_Output`:

- `*_text.txt` - raw extracted text.
- `*_tables.csv` - all extracted tables, when tables are detected.
- `*_payload.xml` - structured payload for downstream LLM/review workflows.
- `*_human_report.pdf` - human-readable extraction report.
- `exceptions.json` - reconciliation status for the whole batch.
- `Quarantine\` - contains outputs for unreconciled documents.

## Configuration

Main config file:

```text
config.ini
```

Important settings:

```ini
[FOLDERS]
input_folder  = OCR_Input
output_folder = OCR_Output

[LANGUAGES]
tesseract_lang = eng+hin+mar
```

Relative folder paths are resolved from the project folder when launched through
the BAT file.

## Packaging For Another Windows System

Before creating the zip, do not include:

```text
.git
.venv
__pycache__
*.pyc
OCR_Input
OCR_Output
```

Zip the project folder after cleanup. On the other Windows system:

1. Extract the zip.
2. Install Python and Tesseract.
3. Double-click `Install_Dependencies.bat`.
4. Double-click `Run_OCR_Utility.bat`.
5. If there is an error, double-click `Check_Setup.bat`.

## Troubleshooting

`python is not recognized`

Install Python again and tick `Add python.exe to PATH`.

`TesseractNotFoundError`

Install Tesseract to:

```text
C:\Program Files\Tesseract-OCR\tesseract.exe
```

`Failed loading language 'eng'`

Make sure this file exists:

```text
RCB_Utility\tessdata\eng.traineddata
```

If it is missing, your zip did not include the full `tessdata` folder.

Azure errors

Check `AZURE_DOCUMENT_ENDPOINT` and `AZURE_DOCUMENT_KEY`, or leave Azure blank
and run local OCR only.

Blank or garbled Indic text in PDF reports

Keep `FreeSans.ttf` in the project root.
