# LogoRemover

Batch-remove the JuiceBox logo from hundreds of PDF resumes in one click.

- **Fully offline.** No uploads, no accounts, no subscriptions.
- **Originals are never modified.** Cleaned copies go to `<your-folder>/cleaned/`, plus a `report.txt`.
- **It will not silently damage a resume.** Every cleaned copy is compared with its original. If anything other than the word "Juicebox" went missing, the copy is discarded and the untouched original is copied instead (reported as `REVERTED`).
- **One bad PDF never stops the batch** — it is listed as `SKIPPED` in the report.
- Optionally moves originals that had a logo to the Trash / Recycle Bin (recoverable) — only after the cleaned copy has been verified.

## What it removes

| Target | How it is recognised |
|---|---|
| Vector-drawn header logo (the real JuiceBox export) | small, centered cluster of vector shapes in the top 15% of **page 1**; never touches full-width dividers, and never touches anything that has text on it |
| Text wordmark "Juicebox" | the word in the header band (top 30%, roughly centered) plus the icon next to it |
| Repeated image logo | the same small image at the same spot on most pages |
| Watermark annotations | `/Watermark` annotations |

Header photos, contact icons, name banners and body content are left alone.
Pages with a rotation (`/Rotate`) are not scanned for header logos.

---

## For end users (no experience needed)

You will receive `LogoRemover-windows.zip` (Windows) or a `.dmg` (Mac).

### Windows

1. Unzip `LogoRemover-windows.zip` (right-click → Extract All).
2. Open the folder and double-click `LogoRemover.exe`.
3. **First run only** (the app is unsigned): if Windows says *"Windows protected your PC"*, click **More info** → **Run anyway**.

### Mac

There are two Mac builds — use the one that matches your Mac (Apple menu → **About This Mac**):

- **`LogoRemover-apple-silicon.dmg`** — Macs with an M1, M2, M3, M4… chip
- **`LogoRemover-intel.dmg`** — Macs with an Intel processor

1. Double-click the `.dmg` and drag **LogoRemover** into **Applications**.
2. **First run only** (the app is unsigned):
   - **macOS 15 (Sequoia) or newer:** double-click LogoRemover. When macOS blocks it, click **Done/Cancel**, open **System Settings → Privacy & Security**, scroll down to *Security*, click **Open Anyway** next to LogoRemover, then confirm.
   - **macOS 14 or older:** right-click (or Control-click) LogoRemover → **Open** → **Open**.
   - If macOS says the app is *"damaged"*, open Terminal and run:
     `xattr -dr com.apple.quarantine /Applications/LogoRemover.app`

### Using the app (both systems)

1. Click **Choose folder…** and pick the folder with the PDF resumes.
2. Leave **"Move originals that had a logo to Trash"** ticked if you want the originals out of the way (recoverable), or untick it to keep both copies.
3. Click **Clean PDFs**, then **Open cleaned files**.

Cleaned PDFs are in `<your-folder>/cleaned/`. Only the PDFs directly inside the chosen folder are processed (not sub-folders).

---

## For the maintainer

### Files to upload to the repo

Replace/add these, keeping the folder structure:

```
app.py
remove_logos.py
requirements.txt
logo-remover.spec
README.md
.gitignore
tests/test_engine.py
.github/workflows/build.yml
```

### Builds (GitHub Actions — free, no build machine needed)

Every push to `main` (and every pull request) runs `.github/workflows/build.yml`:

1. **Unit tests** (Linux, then again on Windows and macOS).
2. **PyInstaller build** for Windows, macOS Apple Silicon and macOS Intel.
3. **Self-test of the built app** — the freshly built `.exe` / `.app` is launched with `--selftest`, which runs the cleaning engine on generated PDFs, checks `send2trash` and opens a Tk window. If the packaged app is broken, the job fails and **no artifact is published**.
4. The macOS app is ad-hoc signed (required for Apple Silicon) and packed into a drag-to-Applications `.dmg`.

Download from **Actions → latest "Build LogoRemover" run → Artifacts**:

- `LogoRemover-windows` → `LogoRemover-windows.zip`
- `LogoRemover-mac-apple-silicon` → `LogoRemover-apple-silicon.dmg`
- `LogoRemover-mac-intel` → `LogoRemover-intel.dmg`

> The Intel Mac job uses the `macos-15-intel` runner, which GitHub has announced it will retire in Fall 2027. If you no longer need Intel Macs, delete that entry from the `matrix` in `build.yml`.

### Command line / development

```bash
pip install -r requirements.txt
python3 remove_logos.py /path/to/resumes            # -> /path/to/resumes/cleaned/
python3 remove_logos.py /path/to/resumes --out /somewhere/else
python3 remove_logos.py --selftest                  # built-in engine check
python3 -m unittest discover -s tests -v            # unit tests (synthetic PDFs only)
python3 app.py                                      # run the GUI
```

Tuning knobs (top of `remove_logos.py`): `WORD`, `HEADER_PAGES`, `VECTOR_BAND`, `VECTOR_MAX_W/H`, `WORDMARK_BAND`, `REPEAT_SHARE`, `IMAGE_MAX_AREA`.
To keep originals by default, change `self.delete_originals = tk.BooleanVar(value=True)` to `value=False` in `app.py`.

### Notes

- Requirements are just `pymupdf` and `send2trash` (the old `pypdf` dependency is gone).
- Password-protected PDFs are skipped. PDFs with only an owner password (printing restrictions) are cleaned, and the cleaned copy has that encryption removed.
- Don't commit real resumes to the repo — the tests generate their own synthetic PDFs.

### Privacy

The cleaner runs 100% locally. Resumes are never uploaded anywhere.
