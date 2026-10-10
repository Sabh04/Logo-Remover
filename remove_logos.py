#!/usr/bin/env python3
"""Batch-remove the Juicebox logo (and watermarks) from PDF resumes.

Engine used by both the desktop app (app.py) and the command line.
Only depends on PyMuPDF (pip install -r requirements.txt). Python 3.9+,
Windows / macOS / Linux.

What it removes, per file
-------------------------
1. Vector-drawn header logo: the real Juicebox export draws its logo as vector
   paths (not text, not an image). A small, centered cluster of vector
   drawings in the top 15% of the FIRST page is whited out.
     * full-width rules / dividers are kept
     * a cluster that overlaps ANY text is never touched (protects name
       banners and similar designs)
2. Text wordmark: the word "Juicebox" in the header band (top 30%, roughly
   centered), plus an icon right next to it.
3. Repeated image logos: an image that appears at the same spot on most pages
   and is small (agency header/footer logo).
4. /Watermark annotations.

Safety guarantees
-----------------
* Original files are NEVER modified, and nothing is written next to them.
  Cleaned copies go to <input_dir>/cleaned/ (plus report.txt).
* After cleaning, the copy is compared with the original. If any text other
  than the word "Juicebox" went missing, the cleaned copy is discarded and
  the untouched original is copied instead (reported as REVERTED).
* One bad PDF never stops the batch; it is reported as SKIPPED.

Usage
-----
    python3 remove_logos.py /path/to/resumes [--out /path/to/out]
    python3 remove_logos.py --selftest
"""

import argparse
import math
import os
import shutil
import sys
import tempfile
from collections import Counter, defaultdict

try:
    import pymupdf
except ImportError:  # PyMuPDF < 1.24.3 only ships the legacy name
    import fitz as pymupdf

__version__ = "2.0.0"

try:  # keep MuPDF's console chatter out of the way (windowed apps, CI logs)
    pymupdf.TOOLS.mupdf_display_errors(False)
except Exception:
    pass

# ---------------------------------------------------------------- settings --
WORD = "juicebox"          # text wordmark to look for
HEADER_PAGES = 1           # vector/wordmark detection only on the first N pages
VECTOR_BAND = 0.15         # top fraction of the page searched for vector logos
VECTOR_MAX_W = 0.35        # logo cluster must be narrower than this * page width
VECTOR_MAX_H = 0.06        # ...and shorter than this * page height
WORDMARK_BAND = 0.30       # top fraction searched for the text wordmark
REPEAT_SHARE = 0.70        # image must be on >= this share of pages
IMAGE_MAX_AREA = 0.12      # repeated-image logo must cover < this * page area

_WHITE = (1, 1, 1)


# ---------------------------------------------------------------- helpers ---
def _text_words(page):
    return [pymupdf.Rect(w[:4]) for w in page.get_text("words")]


def _overlaps(rect, others):
    for o in others:
        inter = rect & o
        if not inter.is_empty:
            return True
    return False


def _redact(page, rects, images, graphics, text):
    """Apply white redactions for rects with explicit removal modes."""
    for r in rects:
        page.add_redact_annot(r, fill=_WHITE)
    page.apply_redactions(images=images, graphics=graphics, text=text)


# ------------------------------------------------------- 1. vector logo -----
def _vector_logo_rects(page):
    r = page.rect
    W, H = r.width, r.height
    band_y = r.y0 + H * VECTOR_BAND

    cands = []
    for d in page.get_drawings():
        q = d["rect"]
        if q.y1 > band_y:
            continue
        if (q.x1 - q.x0) >= 0.5 * W:      # rules / dividers span the width
            continue
        if (q.y1 - q.y0) > 0.08 * H:      # too tall to be a compact logo
            continue
        cands.append(q)

    # cluster nearby drawings (letters / icon are separate paths)
    clusters = []
    for q in sorted(cands, key=lambda q: q.x0):
        for cl in clusters:
            if not (q.x1 < cl[0] - 12 or q.x0 > cl[2] + 12 or
                    q.y1 < cl[1] - 12 or q.y0 > cl[3] + 12):
                cl[0] = min(cl[0], q.x0)
                cl[1] = min(cl[1], q.y0)
                cl[2] = max(cl[2], q.x1)
                cl[3] = max(cl[3], q.y1)
                break
        else:
            clusters.append([q.x0, q.y0, q.x1, q.y1])

    words = _text_words(page)
    rects = []
    for x0, y0, x1, y1 in clusters:
        cx = (x0 + x1) / 2
        if (x1 - x0) >= VECTOR_MAX_W * W or (y1 - y0) > VECTOR_MAX_H * H:
            continue
        if not (W * 0.30 <= cx <= W * 0.70):
            continue
        rect = pymupdf.Rect(x0 - 4, y0 - 4, x1 + 4, y1 + 4)
        if _overlaps(rect, words):         # never touch anything with text on it
            continue
        rects.append(rect)
    return rects


# ------------------------------------------------------ 2. text wordmark ----
def _wordmark_hits(page, word):
    r = page.rect
    top_edge = r.y0 + r.height * WORDMARK_BAND
    seen, hits = set(), []
    for h in page.search_for(word):      # PyMuPDF search is case-insensitive
        key = (round(h.x0, 1), round(h.y0, 1), round(h.x1, 1), round(h.y1, 1))
        if key in seen:
            continue
        seen.add(key)
        cx = (h.x0 + h.x1) / 2
        if h.y1 <= top_edge and r.width * 0.25 <= cx <= r.width * 0.75:
            hits.append(h)
    return hits


def _wordmark_rect(page, h):
    """Expand a wordmark text hit to cover the icon sitting next to it."""
    pad_v = h.height * 0.45
    rect = pymupdf.Rect(h.x0 - h.height * 1.8, h.y0 - pad_v,
                        h.x1 + h.height * 0.6, h.y1 + pad_v)
    for d in page.get_drawings():
        dr = d["rect"]
        if (abs(dr.y0 - h.y0) < h.height * 1.5 and dr.x1 <= h.x0 + 2
                and dr.x0 >= h.x0 - h.height * 3.5):
            rect |= dr
    for info in page.get_image_info():
        ib = pymupdf.Rect(info["bbox"])
        if (abs(ib.y0 - h.y0) < h.height * 1.5 and ib.x1 <= h.x0 + 2
                and ib.x0 >= h.x0 - h.height * 3.5):
            rect |= ib
    return rect


# ------------------------------------------------ 3. repeated image logos ----
def _repeated_image_rects(doc):
    """{page_no: [rects]} for images that repeat like an agency logo."""
    n = doc.page_count
    if n < 2:
        return {}
    placements = defaultdict(list)       # digest -> [(page_no, rect)]
    for pno in range(n):
        try:
            infos = doc[pno].get_image_info(hashes=True)
        except Exception:
            continue
        for info in infos:
            dg, bb = info.get("digest"), info.get("bbox")
            if dg and bb:
                placements[dg].append((pno, pymupdf.Rect(bb)))

    out = defaultdict(list)
    for pls in placements.values():
        pages = {p for p, _ in pls}
        if len(pages) < max(2, math.ceil(REPEAT_SHARE * n)):
            continue
        cxs = sorted((r.x0 + r.x1) / 2 for _, r in pls)
        cys = sorted((r.y0 + r.y1) / 2 for _, r in pls)
        mx, my = cxs[len(cxs) // 2], cys[len(cys) // 2]
        if not all(abs((r.x0 + r.x1) / 2 - mx) < 8 and
                   abs((r.y0 + r.y1) / 2 - my) < 8 for _, r in pls):
            continue
        if any(r.width * r.height >= IMAGE_MAX_AREA * doc[p].rect.width *
               doc[p].rect.height for p, r in pls):
            continue
        for p, r in pls:
            out[p].append(pymupdf.Rect(r.x0 - .5, r.y0 - .5, r.x1 + .5, r.y1 + .5))
    return out


# --------------------------------------------------- 4. watermark annots ----
def _remove_watermarks(page):
    n = 0
    for a in list(page.annots() or []):
        if a.type[0] == pymupdf.PDF_ANNOT_WATERMARK:
            page.delete_annot(a)
            n += 1
    return n


# ---------------------------------------------------------- verification ----
def _word_counter(doc):
    c = Counter()
    for page in doc:
        for w in page.get_text("words"):
            c[w[4].casefold()] += 1
    return c


def verify_output(src, dst):
    """(ok, reason). ok only if dst has the same page count as src and kept
    every word of src (except the word 'Juicebox' itself)."""
    try:
        with pymupdf.open(src) as a, pymupdf.open(dst) as b:
            if b.page_count == 0 or a.page_count != b.page_count:
                return False, "page count changed"
            lost = _word_counter(a) - _word_counter(b)
            lost.pop(WORD, None)
            if lost:
                sample = ", ".join(list(lost)[:5])
                return False, f"text would have been lost ({sample})"
        return True, ""
    except Exception as e:
        return False, f"could not verify output: {e}"


# ------------------------------------------------------------- one file ----
def process_pdf(src, dst):
    """Clean one PDF from src to dst. Never raises.

    Returns a report dict: file, watermarks, image_logos, vector_logos,
    wordmarks, had_logo, error, notes. When error is set nothing was written.
    """
    rep = {"file": os.path.basename(src), "watermarks": 0, "image_logos": 0,
           "vector_logos": 0, "wordmarks": 0, "had_logo": False,
           "error": None, "notes": []}
    doc = None
    part = dst + ".part"
    try:
        doc = pymupdf.open(src)
        if doc.needs_pass and not doc.authenticate(""):
            rep["error"] = "password-protected"
            return rep
        if doc.page_count == 0:
            rep["error"] = "no pages"
            return rep

        # image logos first (needs the whole document)
        for pno, rects in _repeated_image_rects(doc).items():
            _redact(doc[pno], rects, pymupdf.PDF_REDACT_IMAGE_PIXELS,
                    pymupdf.PDF_REDACT_LINE_ART_NONE, pymupdf.PDF_REDACT_TEXT_NONE)
            rep["image_logos"] += len(rects)

        for pno, page in enumerate(doc):
            rep["watermarks"] += _remove_watermarks(page)

            if page.rotation:
                if pno < HEADER_PAGES:
                    rep["notes"].append(f"page {pno + 1} is rotated: header scan skipped")
                continue

            if pno < HEADER_PAGES:
                rects = _vector_logo_rects(page)
                if rects:
                    _redact(page, rects, pymupdf.PDF_REDACT_IMAGE_NONE,
                            pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                            pymupdf.PDF_REDACT_TEXT_NONE)
                    rep["vector_logos"] += len(rects)

            hits = _wordmark_hits(page, WORD)
            if hits:
                rects = [_wordmark_rect(page, h) for h in hits]
                _redact(page, rects, pymupdf.PDF_REDACT_IMAGE_PIXELS,
                        pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                        pymupdf.PDF_REDACT_TEXT_REMOVE)
                rep["wordmarks"] += len(rects)

        changed = bool(rep["watermarks"] or rep["image_logos"] or
                       rep["vector_logos"] or rep["wordmarks"])

        if not changed:
            doc.close()
            doc = None
            shutil.copyfile(src, dst)          # byte-for-byte copy
            return rep

        if doc.is_encrypted:
            rep["notes"].append("encryption removed from the copy")
        doc.save(part, garbage=3, deflate=True,
                 encryption=pymupdf.PDF_ENCRYPT_NONE)
        doc.close()
        doc = None

        ok, reason = verify_output(src, part)
        if not ok:
            os.remove(part)
            shutil.copyfile(src, dst)
            rep.update(watermarks=0, image_logos=0, vector_logos=0, wordmarks=0)
            rep["notes"].append(f"REVERTED: kept original unchanged - {reason}")
            return rep

        os.replace(part, dst)
        rep["had_logo"] = True
        return rep
    except Exception as e:
        rep["error"] = f"{type(e).__name__}: {e}"
        return rep
    finally:
        try:
            if doc is not None:
                doc.close()
        except Exception:
            pass
        try:
            if os.path.exists(part):
                os.remove(part)
        except Exception:
            pass


# ------------------------------------------------------------- the batch ----
def clean_pdfs(input_dir, out_dir=None, progress_callback=None, log_callback=None):
    """Batch-clean PDFs. Importable engine for the GUI and the CLI.

    progress_callback(current, total, filename) and log_callback(message)
    are optional. Returns {done, skipped, out_dir, lines, details} where
    details is a list of {fname, src, dst, had_logo, skipped, error}.
    """
    in_dir = os.path.abspath(input_dir)
    if not os.path.isdir(in_dir):
        raise FileNotFoundError(f"Folder not found: {in_dir}")
    out_dir = os.path.abspath(out_dir) if out_dir else os.path.join(in_dir, "cleaned")
    if os.path.normcase(out_dir) == os.path.normcase(in_dir):
        raise ValueError("Output folder must be different from the input folder "
                         "(originals are never overwritten).")
    os.makedirs(out_dir, exist_ok=True)

    def _log(msg):
        if log_callback:
            try:
                log_callback(msg)
            except Exception:
                pass

    pdfs = sorted((f for f in os.listdir(in_dir)
                   if f.lower().endswith(".pdf") and
                   os.path.isfile(os.path.join(in_dir, f))), key=str.lower)
    total = len(pdfs)
    if not pdfs:
        _log(f"No PDFs found in {in_dir}")
        return {"done": 0, "skipped": 0, "out_dir": out_dir, "lines": [], "details": []}

    lines, details = [], []
    done = skipped = 0
    for idx, fname in enumerate(pdfs, start=1):
        src = os.path.join(in_dir, fname)
        dst = os.path.join(out_dir, fname)
        if progress_callback:
            try:
                progress_callback(idx, total, fname)
            except Exception:
                pass
        _log(f"[{idx}/{total}] {fname}")

        rep = process_pdf(src, dst)
        if rep["error"]:
            skipped += 1
            msg = f"{fname}: SKIPPED ({rep['error']})"
            details.append({"fname": fname, "src": src, "dst": None,
                            "had_logo": False, "skipped": True, "error": rep["error"]})
        else:
            done += 1
            msg = (f"{fname}: watermarks={rep['watermarks']}, "
                   f"image_logos={rep['image_logos']}, "
                   f"vector_logos={rep['vector_logos']}, wordmarks={rep['wordmarks']}")
            if rep["notes"]:
                msg += " | " + "; ".join(rep["notes"])
            details.append({"fname": fname, "src": src, "dst": dst,
                            "had_logo": rep["had_logo"], "skipped": False, "error": None})
        lines.append(msg)
        _log(msg)

    summary = f"{done} cleaned -> {out_dir} | {skipped} skipped"
    _log(summary)
    try:
        with open(os.path.join(out_dir, "report.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + f"\n\n{summary}\n")
    except Exception as e:
        _log(f"Could not write report.txt: {e}")
    return {"done": done, "skipped": skipped, "out_dir": out_dir,
            "lines": lines, "details": details}


# ------------------------------------------------------------- selftest ----
def _logo_like(page, cx=298.0, cy=50.0):
    """Draw a Juicebox-like vector mark (icon + wordmark blobs) centered at cx."""
    s = page.new_shape()
    s.draw_circle(pymupdf.Point(cx - 44, cy), 8)
    s.finish(fill=(0, 0, 0), color=None)
    for i in range(7):
        s.draw_rect(pymupdf.Rect(cx - 28 + i * 11, cy - 6, cx - 21 + i * 11, cy + 6))
        s.finish(fill=(0, 0, 0), color=None)
    s.commit()


def _ink(page, clip):
    pix = page.get_pixmap(dpi=72, clip=clip, alpha=False)
    return sum(1 for b in pix.samples if b < 250)


def make_sample_resume(path, name="Selftest Person", banner=False, pages=1):
    """Synthetic Juicebox-style export used by the self-test and unit tests."""
    d = pymupdf.open()
    for i in range(pages):
        p = d.new_page(width=595, height=842)
        if i == 0:
            if banner:
                p.draw_rect(pymupdf.Rect(200, 40, 400, 90), color=(.1, .3, .6),
                            fill=(.1, .3, .6))
                p.insert_text((232, 72), "BANNER NAME", fontsize=18, color=(1, 1, 1))
            else:
                _logo_like(p)
            p.draw_line(pymupdf.Point(48, 82), pymupdf.Point(547, 82),
                        color=(.8, .8, .8), width=1)
            p.insert_text((48, 150), name, fontsize=26)
            p.insert_text((48, 180), "Sales Associate at Example Store", fontsize=11)
        else:
            for k in range(5):  # centered dots near the top of page 2
                p.draw_circle(pymupdf.Point(270 + k * 14, 60), 4, fill=(0, 0, 0))
            p.insert_text((48, 150), "Page two body text", fontsize=12)
    d.save(path)
    d.close()


def selftest():
    """End-to-end check of the engine. Returns (ok, message)."""
    tmp = tempfile.mkdtemp(prefix="logoremover_selftest_")
    try:
        in_dir = os.path.join(tmp, "in")
        os.makedirs(in_dir)
        make_sample_resume(os.path.join(in_dir, "logo.pdf"), pages=2)
        make_sample_resume(os.path.join(in_dir, "banner.pdf"), name="Banner Person",
                           banner=True)
        res = clean_pdfs(in_dir)
        if res["done"] != 2 or res["skipped"]:
            return False, f"expected 2 cleaned/0 skipped, got {res['done']}/{res['skipped']}"

        logo_box = pymupdf.Rect(230, 35, 370, 65)
        rule_box = pymupdf.Rect(60, 78, 540, 86)
        with pymupdf.open(os.path.join(in_dir, "logo.pdf")) as a, \
                pymupdf.open(os.path.join(res["out_dir"], "logo.pdf")) as b:
            if _ink(a[0], logo_box) == 0:
                return False, "test fixture is broken (no logo drawn)"
            if _ink(b[0], logo_box) != 0:
                return False, "logo was NOT removed"
            if _ink(b[0], rule_box) != _ink(a[0], rule_box):
                return False, "divider line was damaged"
            if _ink(b[1], pymupdf.Rect(250, 50, 350, 70)) != \
                    _ink(a[1], pymupdf.Rect(250, 50, 350, 70)):
                return False, "page 2 content was altered"
            if a[0].get_text() != b[0].get_text() or a[1].get_text() != b[1].get_text():
                return False, "text changed"
        banner_box = pymupdf.Rect(190, 30, 410, 100)
        with pymupdf.open(os.path.join(in_dir, "banner.pdf")) as a, \
                pymupdf.open(os.path.join(res["out_dir"], "banner.pdf")) as b:
            if "BANNER NAME" not in b[0].get_text():
                return False, "name banner text was destroyed"
            if _ink(a[0], banner_box) != _ink(b[0], banner_box):
                return False, "name banner was painted over"
        return True, f"engine OK (v{__version__}, PyMuPDF {pymupdf.__version__})"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------- CLI ----
def main(argv=None):
    ap = argparse.ArgumentParser(description="Batch-remove Juicebox logos/watermarks from PDFs.")
    ap.add_argument("input_dir", nargs="?", help="folder containing the PDFs")
    ap.add_argument("--out", default=None, help="output folder (default: <input>/cleaned)")
    ap.add_argument("--selftest", action="store_true", help="run the built-in self-test and exit")
    args = ap.parse_args(argv)

    if args.selftest:
        ok, msg = selftest()
        print(("PASS: " if ok else "FAIL: ") + msg)
        return 0 if ok else 1
    if not args.input_dir:
        ap.error("input_dir is required (or use --selftest)")
    result = clean_pdfs(args.input_dir, args.out, log_callback=print)
    return 0 if result["skipped"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
