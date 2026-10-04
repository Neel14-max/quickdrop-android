#!/usr/bin/env python3
"""QuickDrop desktop app: drag & drop / paste files to send, scan QR once to pair a phone."""
import os, queue, subprocess, sys, threading, time
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
import qrcode
from PIL import ImageTk
import quickdrop as qd

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:
    DND_FILES = TkinterDnD = None

PORT = 8443
BASE = Path.home() / "QuickDrop"
asks, recv_q = queue.Queue(), queue.Queue()
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
WIN = sys.platform.startswith("win")


def ask_from_thread(who):
    ev, box = threading.Event(), {}
    asks.put((who, ev, box))
    ev.wait(120)
    return box.get("ok", False)


def open_path(p):
    p = Path(p)
    try:
        if WIN:
            os.startfile(p)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except Exception as e:
        messagebox.showerror("QuickDrop", f"Cannot open: {e}")


def clipboard_files():
    """Files copied in Explorer (Ctrl+C) -> list of paths. Windows only."""
    if not WIN:
        return []
    try:
        import ctypes
        from ctypes import wintypes
        u32, s32 = ctypes.windll.user32, ctypes.windll.shell32
        u32.OpenClipboard.argtypes = [wintypes.HWND]
        u32.OpenClipboard.restype = wintypes.BOOL
        u32.GetClipboardData.argtypes = [wintypes.UINT]
        u32.GetClipboardData.restype = wintypes.HANDLE
        s32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
        s32.DragQueryFileW.restype = wintypes.UINT
        files = []
        if not u32.OpenClipboard(None):
            return []
        try:
            h = u32.GetClipboardData(15)  # CF_HDROP
            if h:
                n = s32.DragQueryFileW(h, 0xFFFFFFFF, None, 0)
                for i in range(n):
                    ln = s32.DragQueryFileW(h, i, None, 0)
                    buf = ctypes.create_unicode_buffer(ln + 1)
                    s32.DragQueryFileW(h, i, buf, ln + 1)
                    files.append(buf.value)
        finally:
            u32.CloseClipboard()
        return files
    except Exception:
        return []


def autostart_get():
    if not WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "QuickDrop")
            return True
    except OSError:
        return False


def autostart_set(on):
    import winreg
    cmd = f'"{sys.executable}"' if getattr(sys, "frozen", False) else f'"{sys.executable}" "{os.path.abspath(__file__)}"'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, "QuickDrop", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, "QuickDrop")
            except OSError:
                pass


class App:
    def __init__(self, root):
        self.root, self.tick, self.token, self.ip = root, 0, None, None
        root.title("QuickDrop")
        qd.STATE.update(recv=BASE / "Received", share=BASE / "Share", confirm=True,
                        ask=ask_from_thread, on_received=recv_q.put)
        for p in (qd.STATE["recv"], qd.STATE["share"]):
            p.mkdir(parents=True, exist_ok=True)
        try:
            self.srv, _, self.fp = qd.start_server(PORT)
        except OSError:
            messagebox.showerror("QuickDrop", "QuickDrop is already running (port 8443 is busy).")
            sys.exit(0)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.recv_paths = []

        left = tk.Frame(root, padx=16, pady=14)
        left.grid(row=0, column=0, sticky="n")
        tk.Label(left, text="QuickDrop", font=("Segoe UI", 20, "bold")).pack()
        tk.Label(left, text="Pair your phone (once): open the QuickDrop\napp and tap 'Scan QR code'",
                 font=("Segoe UI", 9), fg="#555").pack(pady=(0, 6))
        self.qr_label = tk.Label(left)
        self.qr_label.pack()
        self.status = tk.Label(left, font=("Segoe UI", 11, "bold"))
        self.status.pack(pady=(8, 0))
        self.addr = tk.Label(left, font=("Segoe UI", 8), fg="#777", justify="center")
        self.addr.pack()

        right = tk.Frame(root, padx=8, pady=14)
        right.grid(row=0, column=1, sticky="n")
        hint = ("Drop files here to send to phone\nor copy files and press Ctrl+V" if DND_FILES
                else "Press Ctrl+V after copying files\nor click Add files")
        self.drop = tk.Label(right, text=hint, font=("Segoe UI", 12), width=42, height=4, relief="ridge",
                             bd=3, bg="#eef4ff", fg="#1d4ed8")
        self.drop.pack(fill="x")
        row = tk.Frame(right)
        row.pack(fill="x", pady=6)
        tk.Button(row, text="Add files...", command=self.pick).pack(side="left")
        tk.Button(row, text="Paste", command=self.paste).pack(side="left", padx=6)
        self.note = tk.Label(row, fg="#16a34a", font=("Segoe UI", 9))
        self.note.pack(side="left", padx=6)

        tk.Label(right, text="Waiting on your phone (tap to open there)", anchor="w",
                 font=("Segoe UI", 9, "bold")).pack(fill="x")
        self.send_list = tk.Listbox(right, height=5, selectmode="extended", activestyle="none")
        self.send_list.pack(fill="x")
        row2 = tk.Frame(right)
        row2.pack(fill="x", pady=4)
        tk.Button(row2, text="Remove selected", command=self.remove).pack(side="left")
        tk.Button(row2, text="Clear all", command=self.clear).pack(side="left", padx=6)

        tk.Label(right, text="Received from phone (double-click to open)", anchor="w",
                 font=("Segoe UI", 9, "bold")).pack(fill="x", pady=(8, 0))
        self.recv_list = tk.Listbox(right, height=5, activestyle="none")
        self.recv_list.pack(fill="x")
        self.recv_list.bind("<Double-Button-1>", self.open_selected)
        row3 = tk.Frame(right)
        row3.pack(fill="x", pady=4)
        tk.Button(row3, text="Open received folder", command=lambda: open_path(qd.STATE["recv"])).pack(side="left")
        tk.Button(row3, text="Forget all phones", command=self.forget).pack(side="left", padx=6)

        self.auto = tk.BooleanVar(value=autostart_get())
        cb = tk.Checkbutton(root, text="Start QuickDrop when Windows starts", variable=self.auto,
                            command=lambda: autostart_set(self.auto.get()))
        cb.grid(row=1, column=0, columnspan=2, pady=(0, 8))
        if not WIN:
            cb.config(state="disabled")

        if DND_FILES:
            try:
                root.drop_target_register(DND_FILES)
                root.dnd_bind("<<Drop>>", lambda e: self.add_paths(root.tk.splitlist(e.data)))
            except Exception:
                pass
        root.bind("<Control-v>", lambda e: self.paste())
        root.protocol("WM_DELETE_WINDOW", lambda: os._exit(0))
        self.draw_qr()
        root.after(300, self.poll)

    # --- sending to phone ---
    def add_paths(self, paths):
        added = skipped = 0
        for raw in paths:
            p = Path(raw)
            if p.is_file():
                if p not in qd.STATE["items"]:
                    qd.STATE["items"].append(p)
                    added += 1
            else:
                skipped += 1
        self.refresh_send()
        msg = f"Added {added} file(s)" if added else ""
        if skipped:
            msg += ("  " if msg else "") + "(folders not supported - zip them first)"
        self.note.config(text=msg)

    def refresh_send(self):
        self.send_list.delete(0, "end")
        for p in qd.STATE["items"]:
            try:
                self.send_list.insert("end", f"{p.name}   ({qd.human(p.stat().st_size)})")
            except OSError:
                self.send_list.insert("end", f"{p.name}   (missing)")

    def pick(self):
        self.add_paths(filedialog.askopenfilenames(title="Choose files to send to phone"))

    def paste(self):
        files = clipboard_files()
        if files:
            self.add_paths(files)
        else:
            self.note.config(text="No files on clipboard - copy files in Explorer first")

    def remove(self):
        for i in sorted(self.send_list.curselection(), reverse=True):
            del qd.STATE["items"][i]
        self.refresh_send()

    def clear(self):
        qd.STATE["items"].clear()
        self.refresh_send()

    # --- receiving ---
    def open_selected(self, _e=None):
        sel = self.recv_list.curselection()
        if sel:
            open_path(self.recv_paths[sel[0]])

    def forget(self):
        if messagebox.askyesno("QuickDrop", "Forget all paired phones? You will need to scan the QR code again."):
            qd.forget_all()

    # --- QR / status ---
    def draw_qr(self):
        self.token, self.ip = qd.STATE["token"], qd.local_ip()
        url = f"https://{self.ip}:{PORT}/c?t={self.token}&fp={self.fp}"
        q = qrcode.QRCode(box_size=6, border=2)
        q.add_data(url)
        q.make(fit=True)
        img = q.make_image(fill_color="black", back_color="white").get_image().convert("RGB")
        self.photo = ImageTk.PhotoImage(img)
        self.qr_label.config(image=self.photo)
        warn = "\n(not on a network - join the phone hotspot!)" if self.ip.startswith("127.") else ""
        self.addr.config(text=f"This PC: {self.ip}{warn}\nReceived files: {qd.STATE['recv']}")

    def poll(self):
        try:
            while True:
                who, ev, box = asks.get_nowait()
                box["ok"] = messagebox.askyesno("QuickDrop", f"Allow phone {who} to pair with this PC?")
                ev.set()
        except queue.Empty:
            pass
        try:
            while True:
                p = recv_q.get_nowait()
                self.recv_paths.insert(0, p)
                self.recv_list.insert(0, f"{p.name}   ({qd.human(p.stat().st_size)})")
        except queue.Empty:
            pass
        n = len(qd.STATE["sessions"])
        if time.time() - qd.STATE["seen"] < 10:
            self.status.config(text="Phone connected", fg="#16a34a")
        elif n:
            self.status.config(text=f"{n} phone(s) paired - open the app", fg="#2563eb")
        else:
            self.status.config(text="Waiting for phone...", fg="#2563eb")
        self.tick += 1
        if qd.STATE["token"] != self.token or (self.tick % 10 == 0 and qd.local_ip() != self.ip):
            self.draw_qr()
        self.root.after(300, self.poll)


if __name__ == "__main__":
    try:
        root = TkinterDnD.Tk() if TkinterDnD else tk.Tk()
    except Exception:
        DND_FILES = None
        root = tk.Tk()
    App(root)
    root.mainloop()
