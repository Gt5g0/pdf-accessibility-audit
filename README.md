# PDF Accessibility Audit Pipeline

## What this tool does

This Python script scans a folder full of PDFs (or downloads them from Box.com), runs the **veraPDF** accessibility checker on every file, and produces a **color-coded Excel report** showing which PDFs pass or fail each checkpoint for the PDF/UA-1 standard.

You can check hundreds of PDFs in minutes instead of opening each one manually.

## Before you start (requirements)

| Software | Why you need it |
|----------|-----------------|
| **Python** 3.8 or newer | Runs the script |
| **Java** 8 or newer | Required by veraPDF |
| **veraPDF** | The actual PDF checker |

## Installation – step by step

### 1. Get the code

```bash
git clone https://github.com/Gt5g0/pdf-accessibility-audit pdf-accessibility-audit
cd pdf-accessibility-audit
```

### 2. Set up a Python virtual environment

**Windows (PowerShell)**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Python dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Install veraPDF

veraPDF is a separate program that checks PDFs for accessibility. You need to download and install it manually.

**Step 4a: Download the installer**
Go to the veraPDF downloads page (`https://software.verapdf.org/releases`) and download the latest **installer ZIP file**. Choose the stable release (not the development build) unless you have a specific reason to use the newer version.

**Step 4b: Run the installer**
The installer ZIP contains everything you need to set up veraPDF. Once you've extracted the ZIP file:

- **Windows:** Double-click the `verapdf-install.bat` file or run it from a command prompt.
- **macOS / Linux:** Open a terminal in the extracted folder and run the bash script with `./verapdf-install`.

The installer will guide you through a few simple steps:
1.  **Choose installation location:** You can accept the default or pick a folder you'll remember.
2.  **Select components:** It's safe to keep all the default options checked.
3.  **Install:** The installer will unpack the files to the folder you chose.

**Step 4c: Find the veraPDF executable**
After installation, find the `bin` folder inside the location you chose. This folder contains the command-line program you'll need to point the audit script to:

- **Windows:** `C:\Program Files\veraPDF\bin\verapdf.bat` (your path may differ)
- **macOS / Linux:** The executable is simply named `verapdf` (e.g., `/Applications/veraPDF/bin/verapdf`)

You can also add this `bin` folder to your system's `PATH` environment variable. If you do, the script can find veraPDF automatically when you set `verapdf_path: auto` in the configuration file.

### 5. Create your configuration file

This repository already includes a working `config.yaml`. Edit that file to point
to your PDFs and choose your scope.

Minimal local example (keys and indentation must match exactly):

```yaml
source: local                      # or "box"
verapdf_path: auto                 # or a full path to verapdf.bat / verapdf
root_folder: "sample_pdfs"         # folder containing PDFs (and optional student subfolders)
output_dir: "reports"
max_processes: 4
disable_error_messages: false
# timeout_seconds: null

scope:
  mode: all                        # scans every *.pdf under root_folder (students list ignored)
  # mode: students                 # scans only the first-level folders listed below
  # students:
  #   - Doe, John
```

### 6. Setting up Box.com as a source

If you want to audit PDFs stored in a Box.com account, you'll need to create a Box application and get a developer token.

**Step 6a: Create a Box App**
1.  Log in to your Box account and go to the Box Developer Console (https://app.box.com/developers/console).
2.  Click **"Create New App"** or **"Create Platform App"**.
3.  For the authentication method, select **"User Authentication (OAuth 2.0)"**. This is the standard option for accessing your own files.
4.  Give your app a name (e.g., "PDF Audit Tool") and click **"Create App"**.

**Step 6b: Generate a Developer Token**
1.  In your new app's settings, go to the **"Configuration"** tab.
2.  Scroll down to the **"Developer Token"** section.
3.  Click **"Generate Developer Token"**.
4.  Copy the long string of characters that appears. This is your token.

**Step 6c: Find your Box Folder ID**
1.  In your Box.com web account, navigate to the folder containing the PDFs you want to audit.
2.  Look at the URL in your browser's address bar. It will end with something like `/folder/123456789012`. The number at the end is your `root_folder_id`. Copy this number.

**Step 6d: Update your config.yaml file**
Now, edit the `config.yaml` file to use Box as the source:

```yaml
source: box
verapdf_path: "C:/Program Files/veraPDF/bin/verapdf.bat"
output_dir: "reports"
max_processes: 4
disable_error_messages: false
# timeout_seconds: null
scope:
  mode: all
box:
  developer_token: "YOUR_COPIED_TOKEN_GOES_HERE"
  root_folder_id: "123456789012"
  staging_dir: "box_staging"
  clear_staging_before_run: true
```

> **Important Note:** Developer Tokens are for testing and development. They are short-lived and **expire after 60 minutes**. If you plan to run the audit regularly or on a large number of files, you'll want to set up a more permanent authentication method (like a JWT application) in the future. For now, the developer token is the simplest way to get started. **Never commit your `config.yaml` file with a live token to a public repository.**

## Running the audit

From the project folder (with your virtual environment activated), run:

```powershell
python audit_pipeline.py
```

To use a different config file:

```powershell
python audit_pipeline.py path\to\my_config.yaml
```

### What happens next

- The script will scan for PDFs, run veraPDF, and create an Excel file in the `output_dir` folder.
- The Excel file is named `accessibility_audit_YYYYMMDD_HHMMSS.xlsx`.
- Open it to see:
  - A **Summary** sheet with each PDF's name, pass/fail status, and counts of passed/failed checkpoints (colored green/red).
  - A separate **Detail** sheet for every PDF, listing exactly which accessibility rules failed.

## Configuration reference

All settings live in `config.yaml`. The most common ones:

| Key | What it does |
|-----|--------------|
| `source` | `local` (files on your computer) or `box` (download from Box.com) |
| `verapdf_path` | Full path to the veraPDF executable, or `auto` |
| `root_folder` | Where to look for PDFs (only for `local` source) |
| `output_dir` | Where to save the Excel report (folder will be created if missing) |
| `max_processes` | How many PDFs to check at once (higher = faster, but uses more CPU) |
| `disable_error_messages` | If `true`, passes `--disableerrormessages` to veraPDF (faster, less verbose) |
| `timeout_seconds` | Optional timeout (seconds) for each veraPDF subprocess run |
| `scope.mode` | `all` = check every PDF; `students` = only check subfolders listed under `scope.students` |
| `scope.students` | List of **first-level folder names** to scan when `scope.mode: students` (indentation must align with `mode:`) |

**Box‑specific settings** (when `source: box`):

| Key | What it does |
|-----|--------------|
| `box.developer_token` | Short‑lived token from the Box Developer Console |
| `box.root_folder_id` | The numeric ID of the Box folder to scan |
| `box.staging_dir` | Local folder where PDFs are temporarily downloaded |
| `box.clear_staging_before_run` | Usually `true` – empties the staging folder before starting |

## Example: running a quick test

1. Create a folder `test_pdfs` with two or three PDFs inside.
2. In `config.yaml` set `root_folder: "test_pdfs"` and `source: local`.
3. Run:

```powershell
python audit_pipeline.py
```

4. Check the `reports` folder for the Excel file.

## Troubleshooting common issues

- **"veraPDF not found"** → Double‑check the `verapdf_path` in `config.yaml`. Use the full path with the correct extension (`.bat` on Windows, no extension on Mac/Linux).
- **"Module not found"** → You forgot to activate the virtual environment or run `pip install -r requirements.txt`.
- **"Permission denied"** → Ensure the `output_dir` folder is writable.
- **Large batch of PDFs freezes** → Lower `max_processes` to `2` or `1`.
- **Box token not working** → Remember that developer tokens expire after 60 minutes. If your run fails with an authentication error, go back to the Box Developer Console and generate a fresh token, then update your `config.yaml` file.

## Contributing

If you'd like to improve the tool, feel free to fork the repository and open a pull request. Please follow the existing code style and include a clear description of your changes.

## License

This project is provided under the **MIT License**. See the `LICENSE` file for details.

## Acknowledgments

- **[veraPDF Consortium](https://verapdf.org/)** for the open‑source PDF/UA validator.
- **PyYAML** and **openpyxl** maintainers for excellent Python libraries.
- **Box** for the `box-sdk-gen` package used in optional cloud ingestion.
