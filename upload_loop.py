from pathlib import Path
from dotenv import load_dotenv
from collections import defaultdict
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
import argparse, os, re, sys, time, datetime as dt

load_dotenv()
REQUIRED_ENV = {
        "UPLOAD_URL": link,
        "OCULO_EMAIL": email,
        "OCULO_PASSW": password,
}

missing = [k for k, v in REQUIRED_ENV.items() if not v]
if missing:
    print(f"Missing env vars: {','.join(missing)} (check .env)")
    sys.exit(1)

EXTS = {".insv", ".lrv", ".mp4"}
PAIR_TIMEOUT_MS = 12 * 60 * 1000  # 12 minutes per pair

DATE_RE = re.compile(r"(\d{8})")        # e.g. 20250816
NNN_RE  = re.compile(r"_(\d+)\.[^.]+$") # trailing _NNN before extension

# ----------------------------- CLI -----------------------------

def parse_args():
    epilog_text = """\
Environment:
  Create a .env file in the project directory (see example.env) and insert your information:

    UPLOAD_URL=https://app.eu.oculo.ai/sites/XXXXXXXX/upload-scan
    OCULO_EMAIL=you@example.com
    OCULO_PASSW=yourpassword

  The .env file is loaded automatically at runtime.
"""

    ap = argparse.ArgumentParser(
        description="Automate Oculo uploads.",
        epilog=epilog_text,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("folder", type=Path, help="Folder with camera files")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--date", help="Only upload files matching YYYYMMDD (default: today)")
    g.add_argument("--nnn", help="Only upload files with trailing numbers in RANGE, e.g. 120-140")
    ap.add_argument("--list", action="store_true", help="List planned uploads and exit")
    ap.add_argument("--move-to", type=Path, help='After success, move both files to this folder (created if missing)')
    ap.add_argument("--headless", action="store_true", help="Run Chromium headless")
    return ap.parse_args()


# -------------------------- Discovery --------------------------

def find_candidates(folder: Path, want_date: str | None, nnn_range: tuple[int,int] | None):
    """Return dict: key=NNN (int), value=[files...] filtered by date/nnn."""
    groups: dict[int, list[Path]] = defaultdict(list)
    for f in sorted(folder.iterdir()):
        if not (f.is_file() and f.suffix.lower() in EXTS):
            continue
        nnnm = NNN_RE.search(f.name)
        if not nnnm:
            continue
        nnn = int(nnnm.group(1))
        if nnn_range and not (nnn_range[0] <= nnn <= nnn_range[1]):
            continue
        if want_date:
            dm = DATE_RE.search(f.name)
            if not dm or dm.group(1) != want_date:
                continue
        groups[nnn].append(f)
    return groups

def build_pairs(groups: dict[int, list[Path]]):
    """Yield (nnn, [a,b]) only if exactly two files exist for that NNN."""
    for nnn in sorted(groups.keys()):
        fs = groups[nnn]
        if len(fs) == 2:
            yield nnn, sorted(fs)
        elif len(fs) == 1:
            print(f"[skip] NNN {nnn}: only one file present -> {fs[0].name}")
        else:
            print(f"[skip] NNN {nnn}: expected 2 files, found {len(fs)} -> {[p.name for p in fs]}")

# --------------------------- Page Ops --------------------------

def fill_scan_description(page):
    """Fill the required description once (e.g., 'Upload DDMMYYYY')."""
    today = dt.date.today().strftime("%d%m%Y")
    description = f"Upload {today}"
    print(f"[info] Filling scan description: {description}")
    page.wait_for_selector('input[placeholder*="description"]', timeout=10000)
    page.fill('input[placeholder*="description"]', description)

def login(page, upload_url, email, password):
    """Navigate to target URL and log in if the form is shown."""
    page.goto(upload_url, wait_until="domcontentloaded")
    if _see_uploader(page):
        return
    try:
        page.wait_for_selector('input[name="username"]', timeout=8000)
        page.fill('input[name="username"]', email)
        page.fill('input[name="password"]', password)
        page.click('button[type="submit"]')
    except PWTimeout:
        pass
    try:
        page.wait_for_url(re.compile(r"/upload-scan($|\?)"), timeout=60000)
    except PWTimeout:
        pass
    _wait_ready_uploader(page)

def _see_uploader(page):
    return page.locator("div.uppy-Dashboard-AddFiles").first.is_visible(timeout=0) if hasattr(page, "locator") else False

def _wait_ready_uploader(page):
    page.wait_for_selector("div.uppy-Dashboard-AddFiles", state="visible", timeout=60000)

# -------------------------- Upload Loop ------------------------

def upload_pair(page, files: list[Path]):
    """Add a pair directly to the hidden <input type=file> (no native dialog)."""
    a, b = files
    print(f"[upload] {a.name} + {b.name}")

    # We deliberately DO NOT click the 'Browse files' button to avoid opening
    # the OS file picker. Instead we set files straight on the hidden input;
    # Playwright fires the proper 'change' event for Uppy.
    items = page.locator("div.uppy-Dashboard-Item")
    before = items.count()

    file_input = page.locator("div.uppy-Dashboard-AddFiles input[type=file]").first
    file_input.set_input_files([str(a), str(b)])

    # Wait until Uppy reflects the newly queued items (at least +2 tiles)
    try:
        page.wait_for_function(
            "(sel, before) => document.querySelectorAll(sel).length >= before + 2",
            ("div.uppy-Dashboard-Item", before),
            timeout=15000,
        )
    except Exception:
        # Fallback: try to ensure at least one of the filenames is visible in the dashboard
        page.get_by_text(a.name, exact=False).first.wait_for(timeout=5000)

    # Start upload
    try:
        page.get_by_role("button", name=re.compile(r"^\s*upload\b", re.I)).click(timeout=5000)
    except Exception:
        page.locator("button.uppy-StatusBar-actionBtn--upload").click()

    # Wait and finish
    done = page.get_by_role("button", name=re.compile(r"^\s*done\b", re.I))
    done.wait_for(state="visible", timeout=PAIR_TIMEOUT_MS)
    done.click()
    time.sleep(0.5)
    _wait_ready_uploader(page)

# ----------------------------- Main ----------------------------

def main():
    args = parse_args()
    folder = args.folder.expanduser().resolve()
    assert folder.is_dir(), f"Not a directory: {folder}"
    
    # Filter selection
    if args.date:
        want_date = args.date
    elif args.nnn:
        want_date = None
    else:
        want_date = dt.date.today().strftime("%Y%m%d")

    nnn_range = None
    if args.nnn:
        try:
            lo, hi = args.nnn.split("-", 1)
            nnn_range = (int(lo), int(hi))
        except Exception:
            print("Bad --nnn RANGE; use e.g. 120-140"); sys.exit(1)

    groups = find_candidates(folder, want_date, nnn_range)
    plan = list(build_pairs(groups))

    if not plan:
        print("[info] nothing to upload with current filters.")
        sys.exit(0)

    if args.list:
        for nnn, fs in plan:
            print(f"NNN {nnn}: {fs[0].name} + {fs[1].name}")
        sys.exit(0)

    email = os.getenv("OCULO_EMAIL")
    password = os.getenv("OCULO_PASSW")
    upload_url = os.getenv("UPLOAD_URL")
    if not email or not password or not upload_url:
        print("Set UPLOAD_URL, OCULO_EMAIL and OCULO_PASSW env vars."); sys.exit(1)

    move_to = args.move_to
    if move_to:
        move_to.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        ctx = browser.new_context()
        page = ctx.new_page()

        page.goto(upload_url, wait_until="domcontentloaded")
        login(page, upload_url, email, password)
        page.goto(upload_url)
        _wait_ready_uploader(page)
        fill_scan_description(page)

        for nnn, files in plan:
            try:
                upload_pair(page, files)
                if move_to:
                    for f in files:
                        f.rename(move_to / f.name)
            except Exception as e:
                print(f"[warn] NNN {nnn} failed: {e}. Retrying once…")
                page.goto(upload_url)
                _wait_ready_uploader(page)
                upload_pair(page, files)
                if move_to:
                    for f in files:
                        f.rename(move_to / f.name)

        browser.close()
    print("[done] all planned pairs uploaded.")

if __name__ == "__main__":
    main()
