# LogoRemover

Batch-remove the JuiceBox logo from hundreds of PDF resumes in one click.

- Tested on real JuiceBox exports: logo fully gone, all text intact, divider lines and icons untouched.
- Originals are never modified by the cleaner — cleaned copies go to `<your-folder>/cleaned/` plus a `report.txt`.
- Fully offline. No uploads, no subscriptions.
- What it removes: vector-drawn header logo (top 15% centered cluster), text wordmarks in the header, repeated image logos, watermark annotations.

Built from: `app.py` (desktop GUI) + `remove_logos.py` (cleaning engine).

---

## For end users (no experience needed)

You will receive either `LogoRemover-windows.zip` (Windows) or `LogoRemover.dmg` (Mac). Pick your section below.

### Windows

1. Unzip `LogoRemover-windows.zip` (right-click → Extract All).
2. Open the unzipped folder, double-click `LogoRemover.exe`.
3. **First-run warning (one time only, because the app is unsigned):**
   - Windows SmartScreen says "Windows protected your PC".
   - Click **More info** → **Run anyway**.
   - After that it opens like a normal app.
4. In the app:
   - Click **Choose folder…** and pick the folder with your PDF resumes.
   - (Recommended: leave ☑ "Delete originals that had logos" ON — it moves originals to the Recycle Bin, so you can undo.)
   - Click **Clean PDFs**. Watch the progress bar: "Cleaning 45 of 200…"
   - When done, click **Open cleaned files** to see the cleaned copies.
5. Done. Cleaned PDFs are in `<your-folder>/cleaned/`. If you left the checkbox on, originals that had logos are in the Recycle Bin (recoverable).

### macOS

1. Double-click `LogoRemover.dmg` to open it.
2. Drag `LogoRemover.app` into Applications (or double-click it right from the DMG to try it).
3. **First-run warning (one time only, because the app is unsigned):**
   - Right-click (or Control-click) `LogoRemover.app` → **Open** → **Open** in the dialog.
   - After that it opens like a normal app.
4. In the app:
   - Click **Choose folder…** and pick the folder with your PDF resumes.
   - (Recommended: leave ☑ "Delete originals that had logos" ON — it moves originals to Trash, so you can undo.)
   - Click **Clean PDFs**. Watch the progress bar.
   - When done, click **Open cleaned files**.
5. Done. Cleaned PDFs are in `<your-folder>/cleaned/`. Originals that had logos are in Trash (recoverable).

> If the checkbox is OFF, originals are left alone and you get both copies.

---

## For the maintainer (you)

### What to upload to GitHub

Create a **public** repo named `logo-remover` and upload these 5 files/folders (keep the folder structure):

- `app.py`
- `remove_logos.py`
- `requirements.txt`
- `logo-remover.spec`
- `.github/workflows/build.yml` (must stay in `.github/workflows/`)
- `README.md` (optional but recommended)

### Build via GitHub Actions (free, no build machine needed)

1. Push the files to `main` (upload via the GitHub website is fine).
2. Go to the **Actions** tab in your repo → click the latest "Build LogoRemover" run.
3. Wait ~10 minutes for both jobs (Windows + macOS) to turn green.
4. Scroll to **Artifacts** at the bottom of the run:
   - Download `LogoRemover-windows` → contains `LogoRemover-windows.zip`
   - Download `LogoRemover-mac` → contains `LogoRemover.dmg`
5. Send those two files to the end user with the warning-bypass steps above.

To rebuild after a change: just upload the changed file(s) again — Actions rebuilds automatically.

### CLI usage (optional, for testing)

```bash
pip install -r requirements.txt
python3 remove_logos.py /path/to/resumes
# optional: python3 remove_logos.py /path/to/resumes --out /path/to/out
```

Cleaned copies land in `<input>/cleaned/` plus `report.txt`.

### Privacy note

The cleaner runs 100% locally. Resumes are never uploaded anywhere.
