#!/usr/bin/env python3
"""Batch-remove logos and watermarks from PDFs (built for resume batches).

What it removes, per file:
  1. /Watermark annotations (e.g. DRAFT / agency stamps).
  2. Image XObjects that repeat on most pages at a consistent position with a
     small footprint (typical agency header/footer logo), including logos
     nested inside Form XObjects.
  3. On single-page PDFs, small images sitting in the top/bottom margin band
     (likely header/footer logos) -- body photos are kept.
  4. Text wordmarks (e.g. the "Juicebox" header on JuiceBox exports): the
     wordmark text plus its adjacent icon are whited out, but ONLY when found
     in the top header band and roughly centered -- body text mentioning the
     word (e.g. work experience) is never touched.
  5. Vector-drawn logos: the real JuiceBox export draws its logo as vector
     paths (not text, not an image). Small, centered clusters of vector
     drawings in the top 15% of the page are detected and whited out;
     full-width rules/dividers are kept.

Requires: pypdf, pymupdf  (pip install -r requirements.txt)
Works on macOS and Windows with Python 3.9+.

Originals are NEVER modified. Cleaned copies go to <input_dir>/cleaned/ and a
report is printed + saved as <input_dir>/cleaned/report.txt.

Usage:
    python3 remove_logos.py /path/to/resumes [--out /path/to/out]
"""

import argparse
import hashlib
import io
import math
import os
import sys
from collections import defaultdict

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    ContentStream,
    DecodedStreamObject,
    IndirectObject,
    NameObject,
)

IMAGE_OP = b"Do"
CM_OP = b"cm"
PUSH_OP = b"q"
POP_OP = b"Q"

IDENTITY = [1, 0, 0, 1, 0, 0]


def norm_name(n):
    s = str(n)
    return s[1:] if s.startswith("/") else s


def mat_mult(m1, m2):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return [
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2,
    ]


def apply_mat(m, x, y):
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def unit_square_bbox(ctm):
    pts = [apply_mat(ctm, x, y) for x, y in ((0, 0), (1, 0), (0, 1), (1, 1))]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def obj_to_pdf(o):
    if isinstance(o, IndirectObject):
        return f"{o.idnum} {o.generation} R"
    buf = io.BytesIO()
    o.write_to_stream(buf)
    return buf.getvalue().decode("latin-1")


def serialize_ops(ops):
    parts = []
    for operands, operator in ops:
        op = operator.decode("latin-1") if isinstance(operator, bytes) else str(operator)
        parts.append(" ".join(obj_to_pdf(o) for o in operands) + " " + op)
    return ("\n".join(parts) + "\n").encode("latin-1")


def page_size(page):
    mb = page.mediabox
    return float(mb.width), float(mb.height)


def image_name_to_hash(page):
    """Map normalized XObject name -> md5 of decoded image bytes."""
    mapping = {}
    try:
        for img in page.images:
            name = getattr(img, "name", None)
            data = getattr(img, "data", None)
            if name and data:
                h = hashlib.md5(data).hexdigest()
                n = norm_name(name)
                mapping[n] = h
                # pypdf synthesizes names with an image extension appended
                # (e.g. /Im0 -> 'Im0.png'); also index the extensionless form
                for ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".jp2"):
                    if n.lower().endswith(ext):
                        mapping[n[: -len(ext)]] = h
                        break
    except Exception:
        pass
    return mapping


def resolve_xobject(name, resources, reader):
    try:
        xobjs = resources.get("/XObject")
        if xobjs is None:
            return None
        ref = xobjs.get(name if str(name).startswith("/") else "/" + str(name))
        return ref.get_object() if ref is not None else None
    except Exception:
        return None


def collect_placements(content_stream_obj, reader, resources, name_to_hash, ctm, out):
    """Walk a content stream, recording (image_hash, page-space bbox)."""
    try:
        ops = ContentStream(content_stream_obj, reader).operations
    except Exception:
        return
    stack = []
    cur = list(ctm)
    for operands, operator in ops:
        if operator == PUSH_OP:
            stack.append(list(cur))
        elif operator == POP_OP:
            if stack:
                cur = stack.pop()
        elif operator == CM_OP:
            try:
                cur = mat_mult([float(x) for x in operands], cur)
            except Exception:
                pass
        elif operator == IMAGE_OP:
            if not operands:
                continue
            name = str(operands[0])
            xo = resolve_xobject(name, resources, reader)
            if xo is None:
                continue
            if xo.get("/Subtype") == "/Image":
                h = name_to_hash.get(norm_name(name))
                if h:
                    out.append({"hash": h, "bbox": unit_square_bbox(cur)})
            elif xo.get("/Subtype") == "/Form":
                matrix = xo.get("/Matrix")
                sub_ctm = list(cur)
                if matrix is not None:
                    try:
                        sub_ctm = mat_mult([float(x) for x in matrix], cur)
                    except Exception:
                        pass
                sub_res = xo.get("/Resources") or resources
                collect_placements(xo, reader, sub_res, name_to_hash, sub_ctm, out)


def remove_watermark_annots(page):
    annots = page.get("/Annots")
    if not annots:
        return 0
    removed = 0
    kept = ArrayObject()
    for ref in annots:
        try:
            obj = ref.get_object()
        except Exception:
            kept.append(ref)
            continue
        if obj.get("/Subtype") == "/Watermark":
            removed += 1
        else:
            kept.append(ref)
    if removed:
        if kept:
            page[NameObject("/Annots")] = kept
        elif "/Annots" in page:
            del page["/Annots"]
    return removed


def strip_ops(stream_obj, reader, drop_names):
    """Return serialized bytes of stream with logo Do ops removed, or None."""
    try:
        ops = ContentStream(stream_obj, reader).operations
    except Exception:
        return None
    new_ops = []
    changed = False
    for operands, operator in ops:
        if (
            operator == IMAGE_OP
            and operands
            and norm_name(operands[0]) in drop_names
        ):
            changed = True
            continue
        new_ops.append((operands, operator))
    return serialize_ops(new_ops) if changed else None


def replace_stream_data(stream_obj, new_data):
    """New filter-free DecodedStreamObject carrying new_data + copied dict entries."""
    ns = DecodedStreamObject()
    for k, v in stream_obj.items():
        if k in ("/Filter", "/Length"):
            continue
        ns[NameObject(k)] = v
    ns._data = new_data
    return ns


def content_streams(page):
    contents = page.get("/Contents")
    if contents is None:
        return []
    if isinstance(contents, ArrayObject):
        return [s.get_object() for s in contents]
    return [contents.get_object()]


def _wordmark_hits_on_page(page, word):
    """Rects of wordmark text hits in the top header band (centered only)."""
    r = page.rect
    top_edge = r.y0 + r.height * 0.30
    seen = set()
    hits = []
    for variant in (word, word.capitalize(), word.upper()):
        for h in page.search_for(variant):
            key = (round(h.x0, 1), round(h.y0, 1),
                   round(h.x1, 1), round(h.y1, 1))
            if key in seen:
                continue
            seen.add(key)
            cx = (h.x0 + h.x1) / 2
            if h.y1 <= top_edge and r.width * 0.25 <= cx <= r.width * 0.75:
                hits.append(h)
    return hits


def _redact_rect_for_wordmark(page, h):
    """Expand a wordmark text hit to cover its adjacent icon (vector/image)."""
    import pymupdf
    pad_v = h.height * 0.45
    # expand left extra: the cube icon sits left of the wordmark
    rect = pymupdf.Rect(h.x0 - h.height * 1.8, h.y0 - pad_v,
                        h.x1 + h.height * 0.6, h.y1 + pad_v)
    for d in page.get_drawings():
        dr = d["rect"]
        if (abs(dr.y0 - h.y0) < h.height * 1.5
                and dr.x1 <= h.x0 + 2
                and dr.x0 >= h.x0 - h.height * 3.5):
            rect |= dr
    for img in page.get_images(full=True):
        try:
            ib = page.get_image_bbox(img)
        except Exception:
            continue
        if (abs(ib.y0 - h.y0) < h.height * 1.5
                and ib.x1 <= h.x0 + 2
                and ib.x0 >= h.x0 - h.height * 3.5):
            rect |= ib
    return rect


def _vector_logo_rects_on_page(page):
    """Find vector-drawn logos (e.g. the JuiceBox header mark) in the top band.

    The JuiceBox logo is not text and not an image -- it is drawn as vector
    paths. We find it as a cluster of small, roughly centered vector drawings
    in the top 15% of the page. Full-width rules/dividers are excluded, as are
    tall graphics. Returns a list of rects to redact."""
    import pymupdf
    r = page.rect
    W, H = r.width, r.height
    band_y = r.y0 + H * 0.15
    cands = []
    for d in page.get_drawings():
        q = d["rect"]
        if q.y1 > band_y:
            continue
        if (q.x1 - q.x0) >= 0.5 * W:   # rules/dividers span the width; keep
            continue
        if (q.y1 - q.y0) > 0.08 * H:   # too tall to be a compact logo
            continue
        cands.append(q)
    # cluster nearby drawings (the logo's letters/icon are separate paths)
    clusters = []
    for q in sorted(cands, key=lambda q: q.x0):
        placed = False
        for cl in clusters:
            if not (q.x1 < cl["x0"] - 12 or q.x0 > cl["x1"] + 12 or
                    q.y1 < cl["y0"] - 12 or q.y0 > cl["y1"] + 12):
                cl["x0"] = min(cl["x0"], q.x0)
                cl["y0"] = min(cl["y0"], q.y0)
                cl["x1"] = max(cl["x1"], q.x1)
                cl["y1"] = max(cl["y1"], q.y1)
                placed = True
                break
        if not placed:
            clusters.append({"x0": q.x0, "y0": q.y0, "x1": q.x1, "y1": q.y1})
    rects = []
    for cl in clusters:
        cx = (cl["x0"] + cl["x1"]) / 2
        if (cl["x1"] - cl["x0"]) < 0.5 * W and W * 0.30 <= cx <= W * 0.70:
            rects.append(pymupdf.Rect(cl["x0"] - 4, cl["y0"] - 4,
                                      cl["x1"] + 4, cl["y1"] + 4))
    return rects


def fitz_prepass(src_path, word="juicebox"):
    """Single PyMuPDF pre-pass over the header: vector-drawn logos plus text
    wordmarks (+ adjacent icons). Body content is never touched.

    Returns (temp_path or None, {"vector_logos": n, "wordmarks": m}).
    temp_path is a cleaned copy when anything was removed, else None.
    Never raises."""
    empty = {"vector_logos": 0, "wordmarks": 0}
    try:
        import pymupdf
    except Exception:
        return None, empty
    try:
        doc = pymupdf.open(src_path)
    except Exception:
        return None, empty
    counts = {"vector_logos": 0, "wordmarks": 0}
    try:
        for page in doc:
            n_v = n_w = 0
            for rect in _vector_logo_rects_on_page(page):
                page.add_redact_annot(rect, fill=(1, 1, 1))
                n_v += 1
            for h in _wordmark_hits_on_page(page, word):
                page.add_redact_annot(_redact_rect_for_wordmark(page, h),
                                      fill=(1, 1, 1))
                n_w += 1
            if n_v or n_w:
                page.apply_redactions()
            counts["vector_logos"] += n_v
            counts["wordmarks"] += n_w
        if counts["vector_logos"] == 0 and counts["wordmarks"] == 0:
            doc.close()
            return None, counts
        tmp_path = src_path + ".fitz_tmp.pdf"
        doc.save(tmp_path, garbage=3, deflate=True)
        doc.close()
        return tmp_path, counts
    except Exception:
        try:
            doc.close()
        except Exception:
            pass
        return None, {"vector_logos": 0, "wordmarks": 0}


def process_pdf(path):
    """Returns (writer or None, report dict). Never raises on bad files."""
    rep = {"file": os.path.basename(path), "watermarks": 0, "logos": [], "error": None}
    try:
        reader = PdfReader(path)
    except Exception as e:
        rep["error"] = f"unreadable: {e}"
        return None, rep

    n_pages = len(reader.pages)
    if n_pages == 0:
        rep["error"] = "no pages"
        return None, rep

    # NOTE: all mutations happen on the reader's pages BEFORE they are handed
    # to the writer -- PdfWriter snapshots page state at add_page() time.
    pages = list(reader.pages)

    # --- pass 1: watermark annotations + collect image placements ---
    placements = []
    for idx, page in enumerate(pages):
        rep["watermarks"] += remove_watermark_annots(page)
        w, h = page_size(page)
        name_to_hash = image_name_to_hash(page)
        resources = page.get("/Resources") or {}
        for stream_obj in content_streams(page):
            found = []
            collect_placements(
                stream_obj, reader, resources, name_to_hash, IDENTITY, found
            )
            for f in found:
                f.update({"page_idx": idx, "page_w": w, "page_h": h})
                placements.append(f)

    # --- pass 2: decide which image hashes are logos ---
    by_hash = defaultdict(list)
    for pl in placements:
        by_hash[pl["hash"]].append(pl)

    logo_hashes = set()
    for h, pls in by_hash.items():
        page_idxs = {p["page_idx"] for p in pls}
        w, hgt = pls[0]["page_w"], pls[0]["page_h"]
        page_area = w * hgt
        cxs = sorted((p["bbox"][0] + p["bbox"][2]) / 2 for p in pls)
        cys = sorted((p["bbox"][1] + p["bbox"][3]) / 2 for p in pls)
        cx_med, cy_med = cxs[len(cxs) // 2], cys[len(cys) // 2]
        consistent = all(
            abs((p["bbox"][0] + p["bbox"][2]) / 2 - cx_med) < 8
            and abs((p["bbox"][1] + p["bbox"][3]) / 2 - cy_med) < 8
            for p in pls
        )
        max_area = max(
            (p["bbox"][2] - p["bbox"][0]) * (p["bbox"][3] - p["bbox"][1]) for p in pls
        )
        small = max_area < 0.12 * page_area
        repeated = len(page_idxs) >= max(2, math.ceil(0.7 * n_pages))

        single_page_band = False
        if n_pages == 1:
            in_band = cy_med > 0.85 * hgt or cy_med < 0.15 * hgt
            single_page_band = in_band and max_area < 0.08 * page_area

        if (repeated and consistent and small) or single_page_band:
            logo_hashes.add(h)
            rep["logos"].append(
                {
                    "pages": sorted(page_idxs),
                    "band": "header/footer" if single_page_band else "repeated",
                }
            )

    # --- pass 3: strip logo Do ops from page streams and form XObjects ---
    if logo_hashes:
        for page in pages:
            name_to_hash = image_name_to_hash(page)
            drop_names = {n for n, hh in name_to_hash.items() if hh in logo_hashes}
            if not drop_names:
                continue
            contents = page.get("/Contents")
            if isinstance(contents, ArrayObject):
                for i, ref in enumerate(contents):
                    s = ref.get_object()
                    nd = strip_ops(s, reader, drop_names)
                    if nd is not None:
                        contents[i] = replace_stream_data(s, nd)
            elif contents is not None:
                s = contents.get_object()
                nd = strip_ops(s, reader, drop_names)
                if nd is not None:
                    page[NameObject("/Contents")] = replace_stream_data(s, nd)
            # forms nested in page resources
            xobjs = (page.get("/Resources") or {}).get("/XObject") or {}
            form_res_list = []
            for xname in list(xobjs.keys()):
                try:
                    xo = xobjs[xname].get_object()
                except Exception:
                    continue
                if xo.get("/Subtype") == "/Form":
                    nd = strip_ops(xo, reader, drop_names)
                    if nd is not None:
                        xobjs[NameObject(xname)] = replace_stream_data(xo, nd)
                        xo = xobjs[xname]
                    form_res_list.append(xo.get("/Resources") or {})
            # drop orphaned image XObject entries so the logos are truly gone
            for res_dict in [(page.get("/Resources") or {})] + form_res_list:
                xd = res_dict.get("/XObject")
                if xd is None:
                    continue
                for k in [k for k in xd.keys() if norm_name(k) in drop_names]:
                    del xd[k]

    writer = PdfWriter()
    for p in pages:
        writer.add_page(p)

    return writer, rep


def had_logo(rep, pre):
    """True if any logo/watermark was removed for this file."""
    try:
        return (
            rep.get("watermarks", 0) > 0
            or len(rep.get("logos", [])) > 0
            or pre.get("vector_logos", 0) > 0
            or pre.get("wordmarks", 0) > 0
        )
    except Exception:
        return False


def clean_pdfs(input_dir, out_dir=None, progress_callback=None, log_callback=None):
    """Batch-clean PDFs. Importable engine for GUI and CLI.

    Args:
        input_dir: folder containing PDFs
        out_dir: output folder (default: <input_dir>/cleaned)
        progress_callback: callable(current, total, filename) or None
        log_callback: callable(message_str) or None

    Returns:
        dict with keys: done, skipped, out_dir, lines, details
        details is a list of dicts: {fname, src, dst, had_logo, skipped, error}
    """
    in_dir = os.path.abspath(input_dir)
    out_dir = os.path.abspath(out_dir) if out_dir else os.path.join(in_dir, "cleaned")
    os.makedirs(out_dir, exist_ok=True)

    def _log(msg):
        if log_callback:
            try:
                log_callback(msg)
            except Exception:
                pass

    pdfs = sorted(f for f in os.listdir(in_dir) if f.lower().endswith(".pdf"))
    total = len(pdfs)
    if not pdfs:
        _log(f"No PDFs found in {in_dir}")
        return {"done": 0, "skipped": 0, "out_dir": out_dir, "lines": [], "details": []}

    lines = []
    details = []
    done, skipped = 0, 0
    for idx, fname in enumerate(pdfs, start=1):
        src = os.path.join(in_dir, fname)
        if progress_callback:
            try:
                progress_callback(idx, total, fname)
            except Exception:
                pass
        _log(f"[{idx}/{total}] {fname}")
        # pre-pass: header logos (vector-drawn marks + text wordmarks)
        tmp, pre = fitz_prepass(src)
        use_src = tmp if tmp else src
        writer, rep = process_pdf(use_src)
        if tmp:
            try:
                os.remove(tmp)
            except Exception:
                pass
        if writer is None:
            skipped += 1
            msg = f"{fname}: SKIPPED ({rep['error']})"
            lines.append(msg)
            _log(msg)
            details.append({"fname": fname, "src": src, "dst": None,
                            "had_logo": False, "skipped": True, "error": rep.get("error")})
            continue
        dst = os.path.join(out_dir, fname)
        with open(dst, "wb") as f:
            writer.write(f)
        done += 1
        logo_found = had_logo(rep, pre)
        bits = [f"watermarks={rep['watermarks']}", f"logos={len(rep['logos'])}",
                f"vector_logos={pre['vector_logos']}",
                f"wordmarks={pre['wordmarks']}"]
        for lg in rep["logos"]:
            bits.append(f"logo on pages {lg['pages']} ({lg['band']})")
        msg = f"{fname}: " + ", ".join(bits)
        lines.append(msg)
        _log(msg)
        details.append({"fname": fname, "src": src, "dst": dst,
                        "had_logo": logo_found, "skipped": False, "error": None})

    report = "\n".join(lines)
    summary = f"\n{done} cleaned -> {out_dir} | {skipped} skipped"
    _log(summary.strip())
    with open(os.path.join(out_dir, "report.txt"), "w", encoding="utf-8") as f:
        f.write(report + f"\n\n{done} cleaned -> {out_dir} | {skipped} skipped\n")

    return {"done": done, "skipped": skipped, "out_dir": out_dir,
            "lines": lines, "details": details}


def main():
    ap = argparse.ArgumentParser(description="Batch-remove logos/watermarks from PDFs.")
    ap.add_argument("input_dir", help="folder containing the PDFs")
    ap.add_argument("--out", default=None, help="output folder (default: <input>/cleaned)")
    args = ap.parse_args()

    result = clean_pdfs(args.input_dir, args.out,
                        log_callback=print)
    print(f"\n{result['done']} cleaned -> {result['out_dir']} | {result['skipped']} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
