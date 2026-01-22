# Oculo Upload Automation

Automates uploading paired camera files to Oculo using Playwright.

The script:
- Finds matching file pairs based on filename patterns
- Logs into Oculo
- Uploads each pair sequentially
- Optionally moves successfully uploaded files
- Avoids OS file pickers (fully automated)

This is a **personal automation tool**, not an official Oculo client.

---

## Requirements

- Python 3.11+ (recommended)
- Chromium (installed via Playwright)
- A valid Oculo account

---

## Installation

Clone the repository and create a virtual environment:

```bash
git clone https://github.com/yourusername/oculo_upload.git
cd oculo_upload

python -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
playwright install chromium
```

---

## Configuration

This project uses a `.env` file for configuration.

### 1. Create `.env`

Copy the example file:

```bash
cp example.env .env
```

Edit `.env` and fill in real values:

```env
UPLOAD_URL=https://app.eu.oculo.ai/sites/XXXXXXXX/upload-scan
OCULO_EMAIL=you@example.com
OCULO_PASSW=yourpassword
```

> ⚠️ **Never commit `.env`**  
> It is ignored by git. `example.env` is for reference only.

---

## Usage

Basic usage:

```bash
python upload_loop.py /path/to/folder
```

### Options

- `--list`  
  Show which file pairs would be uploaded, then exit.

- `--date YYYYMMDD`  
  Only upload files matching a specific date.

- `--nnn 120-140`  
  Only upload files whose trailing number is within a range.

- `--move-to /path/to/folder`  
  Move files after successful upload.

- `--headless`  
  Run Chromium in headless mode.

Example:

```bash
python upload_loop.py ~/videos --nnn 120-140 --move-to ~/uploaded
```

---

## File Pairing Rules

Files are grouped by a trailing number in the filename:

```
something_123.mp4
something_123.insv
```

A pair is uploaded **only if exactly two matching files exist**.  
Incomplete or ambiguous groups are skipped with a warning.

---

## Safety & Stability Notes

- The script fails fast if required environment variables are missing
- No credentials or URLs are hard-coded
- `.env` is ignored by git
- Uploads are sequential to avoid race conditions

This tool is considered **stable for personal use**.

---

## Disclaimer

This project is not affiliated with or endorsed by Oculo.  
Use at your own risk.
