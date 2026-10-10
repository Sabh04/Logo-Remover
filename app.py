#!/usr/bin/env python3
"""
LogoRemover desktop app - tkinter GUI around the remove_logos.py engine.

Choose a folder -> Clean PDFs -> cleaned copies appear in <folder>/cleaned/.
Optionally moves originals that had a logo to the Trash / Recycle Bin
(recoverable) - but only after the cleaned copy has been verified.

Works on Windows and macOS (and Linux).
Run with --selftest <result-file> to check the installed/frozen app (CI uses this).
"""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import remove_logos
    from remove_logos import clean_pdfs, verify_output
    _ENGINE_ERROR = None
except Exception as _e:  # shown in a dialog instead of dying silently (windowed app)
    remove_logos = clean_pdfs = verify_output = None
    _ENGINE_ERROR = _e


def open_folder_in_manager(path):
    """Open a folder in the OS file manager (Windows/macOS/Linux)."""
    try:
        if sys.platform.startswith("darwin"):
            subprocess.Popen(["open", path])
        elif os.name == "nt":
            os.startfile(path)  # noqa: S606 - Windows-only API
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        messagebox.showerror("Could not open folder", f"{path}\n\n{e}")


class LogoRemoverApp(tk.Tk):
    POLL_MS = 100

    def __init__(self):
        super().__init__()
        self.title("LogoRemover")
        self.geometry("680x560")
        self.minsize(580, 500)

        self.input_dir = tk.StringVar(value="")
        self.delete_originals = tk.BooleanVar(value=True)  # default ON (Trash, recoverable)
        self.is_running = False
        self.last_out_dir = None
        self.msgs = queue.Queue()   # worker thread -> GUI thread (Tk is not thread-safe)

        self._build_ui()
        self._poll_id = self.after(self.POLL_MS, self._poll)

    # ------------------------------------------------------------- UI ----
    def _build_ui(self):
        pad = {"padx": 12, "pady": 6}
        main = ttk.Frame(self, padding=12)
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(0, weight=1)

        ttk.Label(main, text="LogoRemover", font=("TkDefaultFont", 16, "bold")
                  ).grid(row=0, column=0, sticky="w", **pad)
        ttk.Label(main, text="Remove JuiceBox logos from hundreds of PDF resumes in one click. "
                             "Runs fully offline.", wraplength=620
                  ).grid(row=1, column=0, sticky="w", **pad)

        folder_frame = ttk.LabelFrame(main, text="1. Choose folder", padding=10)
        folder_frame.grid(row=2, column=0, sticky="ew", **pad)
        folder_frame.columnconfigure(1, weight=1)
        self.choose_btn = ttk.Button(folder_frame, text="Choose folder…", command=self.choose_folder)
        self.choose_btn.grid(row=0, column=0, padx=(0, 10))
        self.folder_label = ttk.Label(folder_frame, text="No folder selected", foreground="gray")
        self.folder_label.grid(row=0, column=1, sticky="w")

        opts = ttk.LabelFrame(main, text="Options", padding=10)
        opts.grid(row=3, column=0, sticky="ew", **pad)
        self.del_check = ttk.Checkbutton(
            opts,
            text="Move originals that had a logo to Trash / Recycle Bin (recoverable)",
            variable=self.delete_originals)
        self.del_check.pack(anchor="w")

        run_frame = ttk.Frame(main)
        run_frame.grid(row=4, column=0, sticky="ew", **pad)
        run_frame.columnconfigure(0, weight=1)
        self.run_btn = ttk.Button(run_frame, text="2. Clean PDFs", command=self.start_cleaning,
                                  state="disabled")
        self.run_btn.grid(row=0, column=0, sticky="ew", pady=4)

        prog = ttk.Frame(main)
        prog.grid(row=5, column=0, sticky="ew", **pad)
        prog.columnconfigure(0, weight=1)
        self.progress_label = ttk.Label(prog, text="Ready.")
        self.progress_label.grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(prog, mode="determinate", maximum=100)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        log_frame = ttk.LabelFrame(main, text="Status", padding=6)
        log_frame.grid(row=6, column=0, sticky="nsew", **pad)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        main.rowconfigure(6, weight=1)
        self.log_text = tk.Text(log_frame, height=10, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=sb.set)

        bottom = ttk.Frame(main)
        bottom.grid(row=7, column=0, sticky="ew", **pad)
        self.open_btn = ttk.Button(bottom, text="Open cleaned files", command=self.open_cleaned,
                                   state="disabled")
        self.open_btn.pack(side="left")
        self.summary_label = ttk.Label(bottom, text="", foreground="green")
        self.summary_label.pack(side="left", padx=12)

    def log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    # ---------------------------------------------------------- actions ----
    def choose_folder(self):
        if self.is_running:
            return
        d = filedialog.askdirectory(title="Choose folder containing PDF resumes")
        if d:
            self.input_dir.set(d)
            disp = d if len(d) <= 70 else "…" + d[-69:]
            self.folder_label.config(text=disp, foreground="black")
            self.log(f"Selected folder: {d}")
            self.run_btn.config(state="normal")
            self.summary_label.config(text="", foreground="green")
            self.open_btn.config(state="disabled")

    def start_cleaning(self):
        in_dir = self.input_dir.get()
        if not in_dir or not os.path.isdir(in_dir):
            messagebox.showwarning("No folder", "Please choose a folder first.")
            return
        if self.is_running:
            return
        self.is_running = True
        self.run_btn.config(state="disabled")
        self.choose_btn.config(state="disabled")
        self.del_check.config(state="disabled")
        self.open_btn.config(state="disabled")
        self.summary_label.config(text="")
        self.progress["value"] = 0
        self.progress_label.config(text="Starting…")
        self.log(f"--- Starting clean: {in_dir} ---")
        threading.Thread(target=self._worker, args=(in_dir, self.delete_originals.get()),
                         daemon=True).start()

    # ------------------------------------------- worker thread (no Tk!) ----
    def _worker(self, in_dir, delete_on):
        put = self.msgs.put
        try:
            result = clean_pdfs(
                in_dir,
                progress_callback=lambda c, t, f: put(("progress", c, t, f)),
                log_callback=lambda m: put(("log", m)))
        except Exception as e:
            put(("error", f"Error: {e}"))
            return

        trashed = 0
        if delete_on:
            try:
                from send2trash import send2trash
            except Exception:
                send2trash = None
                put(("log", "send2trash not available - originals were left in place."))
            if send2trash:
                for d in result.get("details", []):
                    if d.get("skipped") or not d.get("had_logo") or not d.get("src"):
                        continue
                    ok, why = verify_output(d["src"], d["dst"])
                    if not ok:       # never trash an original unless the copy is verified
                        put(("log", f"Kept original of {d['fname']}: {why}"))
                        continue
                    try:
                        send2trash(d["src"])
                        trashed += 1
                    except Exception as e:
                        put(("log", f"Trash failed for {d['fname']}: {e}"))
                put(("log", f"Moved {trashed} original(s) to Trash (recoverable)."))
        put(("done", result, trashed))

    # ------------------------------------------------ GUI thread: poll ----
    def _poll(self):
        try:
            while True:
                kind, *args = self.msgs.get_nowait()
                if kind == "log":
                    self.log(args[0])
                elif kind == "progress":
                    cur, total, fname = args
                    self.progress["value"] = (cur / total * 100) if total else 0
                    self.progress_label.config(text=f"Cleaning {cur} of {total}… {fname}")
                elif kind == "error":
                    self._finish_with_error(args[0])
                elif kind == "done":
                    self._finish_success(*args)
        except queue.Empty:
            pass
        self._poll_id = self.after(self.POLL_MS, self._poll)

    def destroy(self):
        try:
            self.after_cancel(self._poll_id)
        except Exception:
            pass
        super().destroy()

    def _reset_controls(self):
        self.is_running = False
        self.run_btn.config(state="normal")
        self.choose_btn.config(state="normal")
        self.del_check.config(state="normal")

    def _finish_with_error(self, msg):
        self.log(msg)
        self.progress_label.config(text="Failed.")
        self._reset_controls()
        messagebox.showerror("LogoRemover", msg)

    def _finish_success(self, result, trashed):
        self.last_out_dir = result.get("out_dir")
        done, skipped = result.get("done", 0), result.get("skipped", 0)
        self.progress["value"] = 100
        self.progress_label.config(text=f"Done: {done} cleaned, {skipped} skipped.")
        summary = f"✓ {done} cleaned"
        if trashed:
            summary += f" • {trashed} original(s) moved to Trash"
        if skipped:
            summary += f" • {skipped} skipped (see report.txt)"
        self.summary_label.config(text=summary, foreground="green" if not skipped else "#b36b00")
        self.log(f"--- Finished: {done} cleaned -> {self.last_out_dir} | {skipped} skipped ---")
        self._reset_controls()
        if self.last_out_dir and os.path.isdir(self.last_out_dir):
            self.open_btn.config(state="normal")

    def open_cleaned(self):
        if self.last_out_dir and os.path.isdir(self.last_out_dir):
            open_folder_in_manager(self.last_out_dir)
        else:
            messagebox.showinfo("LogoRemover", "No cleaned folder yet. Run a clean first.")


# ------------------------------------------------------------ selftest -----
def run_selftest(result_path=None):
    """Engine check + Tk check. Used by CI against the frozen Windows/Mac builds."""
    lines, ok = [], True
    if _ENGINE_ERROR is not None:
        lines.append(f"FAIL: engine import: {_ENGINE_ERROR!r}")
        ok = False
    else:
        e_ok, msg = remove_logos.selftest()
        lines.append(("PASS: " if e_ok else "FAIL: ") + msg)
        ok = ok and e_ok
        try:
            import send2trash  # noqa: F401
            lines.append("PASS: send2trash importable")
        except Exception as e:
            lines.append(f"FAIL: send2trash import: {e!r}")
            ok = False
    try:
        root = tk.Tk()
        root.update()
        ver = root.tk.call("info", "patchlevel")
        root.destroy()
        lines.append(f"PASS: Tk {ver} window created")
    except Exception as e:
        lines.append(f"FAIL: Tk: {e!r}")
        ok = False
    text = "\n".join(lines) + "\n"
    if result_path:
        try:
            with open(result_path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass
    try:
        sys.stdout.write(text)
    except Exception:
        pass
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        i = sys.argv.index("--selftest")
        return run_selftest(sys.argv[i + 1] if i + 1 < len(sys.argv) else None)

    if _ENGINE_ERROR is not None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("LogoRemover",
                             f"The cleaning engine could not be loaded:\n\n{_ENGINE_ERROR}")
        return 1

    if os.name == "nt":  # crisp text on high-DPI Windows displays
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    LogoRemoverApp().mainloop()
    return 0


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main())
