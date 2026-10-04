#!/usr/bin/env python3
"""QuickDrop desktop app: double-click, scan the QR with the phone app, transfer files."""
import os, queue, subprocess, sys, threading
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
import qrcode
from PIL import ImageTk
import quickdrop as qd

PORT = 8443
BASE = Path.home() / "QuickDrop"
asks = queue.Queue()
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def ask_from_thread(who):
    """Called from the server thread; the dialog is shown by the GUI thread."""
    ev, box = threading.Event(), {}
    asks.put((who, ev, box))
    ev.wait(120)
    return box.get("ok", False)


def open_folder(p):
    p.mkdir(parents=True, exist_ok=True)
    if sys.platform.startswith("win"):
        os.startfile(p)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


def autostart_get():
    if not sys.platform.startswith("win"):
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
        self.root = root
        root.title("QuickDrop")
        root.resizable(False, False)
        qd.STATE.update(recv=BASE / "Received", share=BASE / "Share", confirm=True, ask=ask_from_thread)
        for p in (qd.STATE["recv"], qd.STATE["share"]):
            p.mkdir(parents=True, exist_ok=True)
        try:
            self.srv, self.ip, self.fp = qd.start_server(PORT)
        except OSError:
            messagebox.showerror("QuickDrop", "QuickDrop is already running (port 8443 is busy).")
            sys.exit(0)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

        f = tk.Frame(root, padx=20, pady=16)
        f.pack()
        tk.Label(f, text="QuickDrop", font=("Segoe UI", 20, "bold")).pack()
        tk.Label(f, justify="left", font=("Segoe UI", 10),
                 text="1. Turn on your phone's hotspot and connect this PC to it.\n"
                      "2. Open the QuickDrop app on the phone and tap 'Scan QR code'.").pack(pady=(4, 8))
        self.qr_label = tk.Label(f)
        self.qr_label.pack()
        self.status = tk.Label(f, font=("Segoe UI", 11, "bold"))
        self.status.pack(pady=(8, 0))
        self.addr = tk.Label(f, font=("Segoe UI", 9), fg="#666")
        self.addr.pack()
        row = tk.Frame(f)
        row.pack(pady=10)
        tk.Button(row, text="Received files", command=lambda: open_folder(qd.STATE["recv"])).grid(row=0, column=0, padx=4)
        tk.Button(row, text="Files to send to phone", command=lambda: open_folder(qd.STATE["share"])).grid(row=0, column=1, padx=4)
        tk.Button(row, text="New QR code", command=self.new_qr).grid(row=0, column=2, padx=4)
        self.auto = tk.BooleanVar(value=autostart_get())
        cb = tk.Checkbutton(f, text="Start QuickDrop when Windows starts", variable=self.auto,
                            command=lambda: autostart_set(self.auto.get()))
        cb.pack()
        if not sys.platform.startswith("win"):
            cb.config(state="disabled")
        root.protocol("WM_DELETE_WINDOW", lambda: os._exit(0))
        self.new_qr()
        root.after(300, self.poll)

    def new_qr(self):
        with qd.STATE["lock"]:
            qd.STATE["token"] = qd.secrets.token_urlsafe(16)
            qd.STATE["session"] = None
        self.ip = qd.local_ip()
        url = f"https://{self.ip}:{PORT}/c?t={qd.STATE['token']}&fp={self.fp}"
        q = qrcode.QRCode(box_size=7, border=2)
        q.add_data(url)
        q.make(fit=True)
        img = q.make_image(fill_color="black", back_color="white").get_image().convert("RGB")
        self.photo = ImageTk.PhotoImage(img)
        self.qr_label.config(image=self.photo)
        warn = "   (not on a network - connect to the hotspot!)" if self.ip.startswith("127.") else ""
        self.addr.config(text=f"This PC: {self.ip}{warn}\nFiles are in: {BASE}")

    def poll(self):
        try:
            while True:
                who, ev, box = asks.get_nowait()
                box["ok"] = messagebox.askyesno("QuickDrop", f"Allow device {who} to connect?")
                ev.set()
        except queue.Empty:
            pass
        if qd.STATE["session"]:
            self.status.config(text="Phone connected", fg="#16a34a")
        else:
            self.status.config(text="Waiting for phone...", fg="#2563eb")
        self.root.after(300, self.poll)


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
