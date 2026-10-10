"""Unit tests for the cleaning engine. Run:  python -m unittest discover -s tests -v

Uses only synthetic PDFs (no personal data) built with PyMuPDF.
"""
import hashlib
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pymupdf  # noqa: E402
import remove_logos as R  # noqa: E402


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def text_of(path):
    with pymupdf.open(path) as d:
        return [p.get_text() for p in d]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lr_test_")
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def p(self, name):
        return os.path.join(self.inp, name)

    def run_clean(self):
        res = R.clean_pdfs(self.inp)
        return res, res["out_dir"]


class TestVectorLogo(Base):
    def test_logo_removed_text_rule_and_page2_kept(self):
        R.make_sample_resume(self.p("a.pdf"), pages=2)
        res, out = self.run_clean()
        self.assertEqual((res["done"], res["skipped"]), (1, 0))
        self.assertTrue(res["details"][0]["had_logo"])
        with pymupdf.open(self.p("a.pdf")) as a, pymupdf.open(os.path.join(out, "a.pdf")) as b:
            box = pymupdf.Rect(230, 35, 370, 65)
            self.assertGreater(R._ink(a[0], box), 0)
            self.assertEqual(R._ink(b[0], box), 0)
            rule = pymupdf.Rect(60, 78, 540, 86)
            self.assertEqual(R._ink(a[0], rule), R._ink(b[0], rule))
            dots = pymupdf.Rect(250, 50, 350, 70)           # page 2 dots untouched
            self.assertEqual(R._ink(a[1], dots), R._ink(b[1], dots))
            self.assertEqual(a[0].get_text(), b[0].get_text())

    def test_name_banner_is_not_destroyed(self):
        R.make_sample_resume(self.p("b.pdf"), name="Real Person", banner=True)
        res, out = self.run_clean()
        self.assertFalse(res["details"][0]["had_logo"])
        self.assertIn("BANNER NAME", text_of(os.path.join(out, "b.pdf"))[0])
        self.assertEqual(sha(self.p("b.pdf")), sha(os.path.join(out, "b.pdf")))  # byte-identical

    def test_header_photo_and_icons_untouched_single_page(self):
        d = pymupdf.open()
        p = d.new_page(width=595, height=842)
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 90, 90), False)
        pix.set_rect(pix.irect, (120, 160, 200))
        p.insert_image(pymupdf.Rect(40, 30, 130, 120), pixmap=pix)
        icon = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 12, 12), False)
        icon.set_rect(icon.irect, (0, 0, 0))
        p.insert_image(pymupdf.Rect(150, 102, 162, 114), pixmap=icon)
        p.insert_text((150, 70), "Jane Photo", fontsize=26)
        d.save(self.p("c.pdf"))
        d.close()
        res, out = self.run_clean()
        self.assertFalse(res["details"][0]["had_logo"])
        with pymupdf.open(os.path.join(out, "c.pdf")) as b:
            self.assertEqual(len(b[0].get_images()), 2)

    def test_rotated_page_is_skipped_with_note(self):
        R.make_sample_resume(self.p("r.pdf"))
        with pymupdf.open(self.p("r.pdf")) as d:
            d[0].set_rotation(90)
            d.save(self.p("rot.pdf"))
        os.remove(self.p("r.pdf"))
        rep = R.process_pdf(self.p("rot.pdf"), os.path.join(self.tmp, "rot_out.pdf"))
        self.assertIsNone(rep["error"])
        self.assertTrue(any("rotated" in n for n in rep["notes"]))
        self.assertFalse(rep["had_logo"])


class TestOtherRemovals(Base):
    def test_text_wordmark_removed_body_kept(self):
        d = pymupdf.open()
        p = d.new_page(width=595, height=842)
        p.draw_circle(pymupdf.Point(255, 56), 7, fill=(0, 0, 0))
        p.insert_text((268, 62), "Juicebox", fontsize=16)
        p.insert_text((48, 200), "Experience at a store", fontsize=12)
        d.save(self.p("w.pdf"))
        d.close()
        res, out = self.run_clean()
        self.assertTrue(res["details"][0]["had_logo"])
        t = text_of(os.path.join(out, "w.pdf"))[0].lower()
        self.assertNotIn("juicebox", t)
        self.assertIn("experience at a store", t)

    def test_repeated_image_logo_removed_on_every_page(self):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 80, 40), False)
        pix.set_rect(pix.irect, (255, 0, 0))
        d = pymupdf.open()
        for i in range(3):
            p = d.new_page(width=595, height=842)
            p.insert_image(pymupdf.Rect(250, 30, 330, 70), pixmap=pix)
            p.insert_text((48, 200), f"Body text page {i}", fontsize=12)
        d.save(self.p("img.pdf"))
        d.close()
        res, out = self.run_clean()
        self.assertTrue(res["details"][0]["had_logo"])
        with pymupdf.open(self.p("img.pdf")) as a:
            self.assertGreater(R._ink(a[0], pymupdf.Rect(250, 30, 330, 70)), 0)  # fixture really has the logo
        with pymupdf.open(os.path.join(out, "img.pdf")) as b:
            for i in range(3):
                self.assertEqual(R._ink(b[i], pymupdf.Rect(250, 30, 330, 70)), 0)
                self.assertIn(f"Body text page {i}", b[i].get_text())

    def test_watermark_annotation_removed(self):
        d = pymupdf.open()
        p = d.new_page()
        p.insert_text((50, 100), "hello world")
        x = d.get_new_xref()
        d.update_object(x, "<</Type/Annot/Subtype/Watermark/Rect[10 10 200 200]>>")
        d.xref_set_key(p.xref, "Annots", f"[{x} 0 R]")
        d.save(self.p("wm.pdf"))
        d.close()
        res, out = self.run_clean()
        self.assertTrue(res["details"][0]["had_logo"])
        with pymupdf.open(os.path.join(out, "wm.pdf")) as b:
            self.assertEqual([a.type[0] for a in b[0].annots()], [])
            self.assertIn("hello world", b[0].get_text())


class TestSafety(Base):
    def test_originals_never_modified_and_nothing_written_beside_them(self):
        R.make_sample_resume(self.p("a.pdf"))
        before = sha(self.p("a.pdf"))
        listing = sorted(os.listdir(self.inp))
        self.run_clean()
        self.assertEqual(sha(self.p("a.pdf")), before)
        self.assertEqual(sorted(os.listdir(self.inp)), sorted(listing + ["cleaned"]))

    def test_bad_file_is_skipped_batch_continues(self):
        R.make_sample_resume(self.p("a.pdf"))
        with open(self.p("bad.pdf"), "w") as f:
            f.write("not a pdf")
        R.make_sample_resume(self.p("z.pdf"))
        res, out = self.run_clean()
        self.assertEqual((res["done"], res["skipped"]), (2, 1))
        self.assertTrue(os.path.exists(os.path.join(out, "z.pdf")))
        self.assertTrue(os.path.exists(os.path.join(out, "report.txt")))

    def test_password_protected_is_skipped(self):
        d = pymupdf.open()
        d.new_page().insert_text((50, 100), "secret")
        d.save(self.p("pw.pdf"), encryption=pymupdf.PDF_ENCRYPT_AES_256,
               owner_pw="o", user_pw="u")
        d.close()
        res, _ = self.run_clean()
        self.assertEqual(res["skipped"], 1)
        self.assertIn("password", res["details"][0]["error"])

    def test_owner_only_encrypted_with_logo_is_cleaned(self):
        R.make_sample_resume(self.p("tmp.pdf"))
        with pymupdf.open(self.p("tmp.pdf")) as d:
            d.save(self.p("enc.pdf"), encryption=pymupdf.PDF_ENCRYPT_AES_256,
                   owner_pw="owner", user_pw="")
        os.remove(self.p("tmp.pdf"))
        res, out = self.run_clean()
        self.assertEqual(res["skipped"], 0)
        self.assertTrue(res["details"][0]["had_logo"])
        with pymupdf.open(os.path.join(out, "enc.pdf")) as b:
            self.assertEqual(R._ink(b[0], pymupdf.Rect(230, 35, 370, 65)), 0)

    def test_text_loss_triggers_revert_to_original(self):
        R.make_sample_resume(self.p("a.pdf"))
        real = R._wordmark_hits
        # force a bad wordmark hit sitting on the candidate's name
        R._wordmark_hits = lambda page, word: [pymupdf.Rect(48, 128, 300, 152)]
        try:
            res, out = self.run_clean()
        finally:
            R._wordmark_hits = real
        self.assertFalse(res["details"][0]["had_logo"])      # original will NOT be trashed
        self.assertIn("REVERTED", res["lines"][0])
        self.assertEqual(sha(self.p("a.pdf")), sha(os.path.join(out, "a.pdf")))

    def test_output_folder_cannot_equal_input(self):
        with self.assertRaises(ValueError):
            R.clean_pdfs(self.inp, self.inp)

    def test_verify_output_detects_missing_text(self):
        R.make_sample_resume(self.p("a.pdf"), name="Alice Example")
        R.make_sample_resume(self.p("b.pdf"), name="Someone Else")
        ok, why = R.verify_output(self.p("a.pdf"), self.p("b.pdf"))
        self.assertFalse(ok)
        self.assertIn("lost", why)

    def test_empty_folder(self):
        res, _ = self.run_clean()
        self.assertEqual((res["done"], res["skipped"]), (0, 0))

    def test_selftest_passes(self):
        ok, msg = R.selftest()
        self.assertTrue(ok, msg)


if __name__ == "__main__":
    unittest.main()
