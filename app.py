#!/usr/bin/env python3
"""
LogoRemover desktop app - tkinter GUI wrapping remove_logos.py engine.

- Big Choose-folder button -> progress bar (Cleaning 45 of 200...) -> done screen
- Checkbox "Delete originals that had logos" (default ON) uses send2trash (recoverable)
- Open-cleaned-files button opens the OS file manager
- Status/log area shows per-file progress

Works on Windows and macOS. No new dependencies beyond requirements.txt.
"""
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import subprocess

# Engine import - refactored remove_logos.py exposes clean_pdfs()
try:
    from remove_logos import clean_pdfs
except ImportError as e:
    # When running as frozen app, ensure clearer error
    raise SystemExit(f"Could not import engine (remove_logos.py): {e}")


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
    def __init__(self):
        super().__init__()
        self.title("LogoRemover")
        self.geometry("640x520")
        self.minsize(560, 480)

        # Style tweaks for clean look on Win/Mac
        style = ttk.Style(self)
        # Use native theme where available
        for theme in ("clam", "aqua", "vista", "xpnative"):
            try:
                if theme in style.theme_names():
                    # Prefer system-like theme; don't force if unavailable
                    pass
            except Exception:
                pass

        self.input_dir = tk.StringVar(value="")
        self.delete_originals = tk.BooleanVar(value=True)  # default ON
        self.is_running = False
        self.last_out_dir = None

        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 12, "pady": 6}

        main = ttk.Frame(self, padding=12)
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(0, weight=1)

        # Title
        title = ttk.Label(main, text="LogoRemover", font=("TkDefaultFont", 16, "bold"))
        title.grid(row=0, column=0, sticky="w", **pad)
        sub = ttk.Label(
            main,
            text="Remove JuiceBox logos from hundreds of PDF resumes in one click.",
            wraplength=600,
        )
        sub.grid(row=1, column=0, sticky="w", **pad)

        # Step 1: folder picker
        folder_frame = ttk.LabelFrame(main, text="1. Choose folder", padding=10)
        folder_frame.grid(row=2, column=0, sticky="ew", **pad)
        folder_frame.columnconfigure(1, weight=1)

        choose_btn = ttk.Button(folder_frame, text="Choose folder…", command=self.choose_folder)
        choose_btn.grid(row=0, column=0, padx=(0, 10))

        self.folder_label = ttk.Label(folder_frame, text="No folder selected", foreground="gray")
        self.folder_label.grid(row=0, column=1, sticky="w")

        # Options
        opts_frame = ttk.LabelFrame(main, text="Options", padding=10)
        opts_frame.grid(row=3, column=0, sticky="ew", **pad)

        del_check = ttk.Checkbutton(
            opts_frame,
            text="Delete originals that had logos (moves to Trash / Recycle Bin — recoverable)",
            variable=self.delete_originals,
        )
        del_check.pack(anchor="w")

        # Step 2: run
        run_frame = ttk.Frame(main)
        run_frame.grid(row=4, column=0, sticky="ew", **pad)
        run_frame.columnconfigure(0, weight=1)

        self.run_btn = ttk.Button(run_frame, text="2. Clean PDFs", command=self.start_cleaning, state="disabled")
        self.run_btn.grid(row=0, column=0, sticky="ew", pady=4)

        # Progress
        prog_frame = ttk.Frame(main)
        prog_frame.grid(row=5, column=0, sticky="ew", **pad)
        prog_frame.columnconfigure(0, weight=1)

        self.progress_label = ttk.Label(prog_frame, text="Ready.")
        self.progress_label.grid(row=0, column=0, sticky="w")

        self.progress = ttk.Progressbar(prog_frame, mode="determinate", maximum=100)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        # Log area
        log_frame = ttk.LabelFrame(main, text="Status", padding=6)
        log_frame.grid(row=6, column=0, sticky="nsew", **pad)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        main.rowconfigure(6, weight=1)

        self.log_text = tk.Text(log_frame, height=10, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        # Bottom buttons
        bottom = ttk.Frame(main)
        bottom.grid(row=7, column=0, sticky="ew", **pad)

        self.open_btn = ttk.Button(bottom, text="Open cleaned files", command=self.open_cleaned, state="disabled")
        self.open_btn.pack(side="left")

        self.summary_label = ttk.Label(bottom, text="", foreground="green")
        self.summary_label.pack(side="left", padx=12)

    def log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def choose_folder(self):
        d = filedialog.askdirectory(title="Choose folder containing PDF resumes")
        if d:
            self.input_dir.set(d)
            # shorten display if very long
            disp = d
            if len(disp) > 70:
                disp = "…" + disp[-69:]
            self.folder_label.config(text=disp, foreground="black")
            self.log(f"Selected folder: {d}")
            self.run_btn.config(state="normal")
            self.summary_label.config(text="")
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
        self.open_btn.config(state="disabled")
        self.summary_label.config(text="")
        self.progress["value"] = 0
        self.progress_label.config(text="Starting…")
        self.log(f"--- Starting clean: {in_dir} ---")

        # Run in background thread so UI stays responsive
        t = threading.Thread(target=self._run_clean_thread, args=(in_dir,), daemon=True)
        t.start()

    def _run_clean_thread(self, in_dir):
        delete_on = self.delete_originals.get()

        def progress_cb(current, total, filename):
            # Called from worker thread -> schedule UI update
            def _update():
                pct = (current / total * 100) if total else 0
                self.progress["value"] = pct
                self.progress_label.config(text=f"Cleaning {current} of {total}… {filename}")
            self.after(0, _update)

        def log_cb(msg):
            self.after(0, lambda: self.log(msg))

        try:
            result = clean_pdfs(in_dir, progress_callback=progress_cb, log_callback=log_cb)
        except Exception as e:
            self.after(0, lambda: self._finish_with_error(f"Error: {e}"))
            return

        # Optional: move originals that had logos to trash (recoverable)
        trashed = 0
        trash_errors = []
        if delete_on:
            try:
                from send2trash import send2trash
            except ImportError:
                self.after(0, lambda: self.log("send2trash not installed — skipping delete-originals step."))
                send2trash = None
            if send2trash:
                for d in result.get("details", []):
                    if not d.get("skipped") and d.get("had_logo") and d.get("src"):
                        try:
                            send2trash(d["src"])
                            trashed += 1
                        except Exception as e:
                            trash_errors.append(f"{d['fname']}: {e}")
                self.after(0, lambda: self.log(f"Moved {trashed} original(s) to Trash (recoverable)."))
                for err in trash_errors:
                    self.after(0, lambda e=err: self.log(f"Trash failed: {e}"))

        self.after(0, lambda: self._finish_success(result, trashed))

    def _finish_with_error(self, msg):
        self.is_running = False
        self.log(msg)
        self.progress_label.config(text="Failed.")
        self.run_btn.config(state="normal")
        messagebox.showerror("LogoRemover", msg)

    def _finish_success(self, result, trashed):
        self.is_running = False
        self.last_out_dir = result.get("out_dir")
        done = result.get("done", 0)
        skipped = result.get("skipped", 0)
        self.progress["value"] = 100
        self.progress_label.config(text=f"Done: {done} cleaned, {skipped} skipped.")
        summary = f"✓ {done} cleaned"
        if trashed:
            summary += f" • {trashed} original(s) moved to Trash"
        if skipped:
            summary += f" • {skipped} skipped"
        self.summary_label.config(text=summary)
        self.log(f"--- Finished: {done} cleaned -> {self.last_out_dir} | {skipped} skipped ---")
        self.run_btn.config(state="normal")
        if self.last_out_dir and os.path.isdir(self.last_out_dir):
            self.open_btn.config(state="normal")

    def open_cleaned(self):
        if self.last_out_dir and os.path.isdir(self.last_out_dir):
            open_folder_in_manager(self.last_out_dir)
        else:
            messagebox.showinfo("LogoRemover", "No cleaned folder yet. Run a clean first.")


def main():
    app = LogoRemoverApp()
    app.mainloop()


if __name__ == "__main__":
    main()
