#!/usr/bin/env python3
"""
QuickDrop server - fast, private phone <-> laptop file transfer over your hotspot.
HTTPS (TLS 1.3), one-time QR pairing, remembered paired phones, laptop-side approval,
SHA-256 of every received file. No cloud, no internet, no mobile data.
CLI:  python quickdrop.py      GUI: quickdrop_gui.py
"""
import argparse, datetime, hashlib, ipaddress, json, os, secrets, socket, ssl
import threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CHUNK = 1024 * 1024
HOME = Path.home() / ".quickdrop"
SESSIONS_FILE = HOME / "sessions.json"
STATE = {"token": secrets.token_urlsafe(16), "sessions": set(), "lock": threading.Lock(),
         "confirm": True, "recv": Path("received"), "share": Path("share"),
         "items": [], "ask": None, "on_received": None, "seen": 0.0}


# ---------- helpers ----------
def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def ensure_cert(ip):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    HOME.mkdir(exist_ok=True)
    cp, kp = HOME / "cert.pem", HOME / "key.pem"
    if not (cp.exists() and kp.exists()):
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "QuickDrop")])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(days=1))
                .not_valid_after(now + datetime.timedelta(days=3650))
                .add_extension(x509.SubjectAlternativeName(
                    [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address(ip))]), False)
                .sign(key, hashes.SHA256()))
        cp.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        kp.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                         serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
        try:
            os.chmod(kp, 0o600)
        except OSError:
            pass
    der = ssl.PEM_cert_to_DER_cert(cp.read_text())
    return cp, kp, hashlib.sha256(der).hexdigest()


def sess_hash(v):
    return hashlib.sha256(v.encode()).hexdigest()


def load_sessions():
    try:
        STATE["sessions"] = set(json.loads(SESSIONS_FILE.read_text()))
    except Exception:
        STATE["sessions"] = set()


def save_sessions():
    HOME.mkdir(exist_ok=True)
    SESSIONS_FILE.write_text(json.dumps(sorted(STATE["sessions"])))


def forget_all():
    STATE["sessions"] = set()
    save_sessions()


def safe_name(raw):
    name = os.path.basename(urllib.parse.unquote(raw or "file")).strip().replace("\x00", "")
    return name or "file"


def unique_path(folder, name):
    p = folder / name
    stem, suf, i = p.stem, p.suffix, 1
    while p.exists():
        p = folder / f"{stem} ({i}){suf}"
        i += 1
    return p


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def shared_files():
    """id -> Path of everything offered to the phone (dragged-in files are shared in place, not copied)."""
    paths = [p for p in STATE["items"] if p.is_file()]
    sh = STATE["share"]
    if sh.is_dir():
        paths += sorted(p for p in sh.iterdir() if p.is_file())
    return {hashlib.sha1(str(p).encode()).hexdigest()[:12]: p for p in paths}


# ---------- web page (used by the phone app and by plain browsers) ----------
PAGE = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>QuickDrop</title><style>
:root{color-scheme:light dark;--b:#2563eb}
body{font-family:system-ui,sans-serif;max-width:560px;margin:0 auto;padding:16px}
h1{font-size:22px;margin:0}h2{font-size:16px;margin-top:26px}
.btn{display:block;width:100%;padding:16px;border:0;border-radius:12px;background:var(--b);
color:#fff;font-size:17px;text-align:center;box-sizing:border-box}
.card{border:1px solid #8884;border-radius:12px;padding:12px;margin:8px 0;font-size:15px;word-break:break-all}
a.file{display:block;color:inherit;text-decoration:none}
a.file b{color:var(--b)}
.bar{height:6px;background:#8883;border-radius:3px;margin-top:6px}.bar i{display:block;height:6px;background:var(--b);border-radius:3px;width:0}
small{opacity:.7}
</style></head><body>
<h1>QuickDrop</h1><small>Encrypted, direct to your laptop. Nothing leaves your hotspot.</small>
<h2>Send to laptop</h2>
<label class=btn>Choose files<input id=f type=file multiple hidden></label>
<div id=up></div>
<h2>From laptop</h2><small>Tap a file to download and open it.</small><div id=dl></div>
<script>
const $=id=>document.getElementById(id);
const h=n=>{for(const u of['B','KB','MB','GB']){if(n<1024)return n.toFixed(1)+' '+u;n/=1024}return n.toFixed(1)+' TB'};
$('f').onchange=async e=>{for(const f of e.target.files)await send(f);e.target.value=''};
function send(f){return new Promise(r=>{
 const d=document.createElement('div');d.className='card';
 d.innerHTML='<b></b><br><span>starting...</span><div class=bar><i></i></div>';
 d.querySelector('b').textContent=f.name;$('up').prepend(d);
 const x=new XMLHttpRequest(),t0=Date.now();
 x.open('POST','/up');x.setRequestHeader('X-Filename',encodeURIComponent(f.name));
 x.upload.onprogress=p=>{const s=p.loaded/((Date.now()-t0)/1000||1);
  d.querySelector('i').style.width=(p.loaded/p.total*100)+'%';
  d.querySelector('span').textContent=h(p.loaded)+' / '+h(p.total)+'  ('+h(s)+'/s)'};
 x.onload=()=>{d.querySelector('span').textContent=x.status==200?'Sent \\u2713':'Failed ('+x.status+')';r()};
 x.onerror=()=>{d.querySelector('span').textContent='Connection error';r()};
 x.send(f)})}
let last='';
async function load(){try{const r=await fetch('/api/files');if(!r.ok)return;const t=await r.text();
 if(t===last)return;last=t;const l=JSON.parse(t),box=$('dl');box.innerHTML='';
 if(!l.length){box.innerHTML='<div class=card><small>Nothing yet. Drag files onto the QuickDrop window on your laptop and they appear here instantly.</small></div>';return}
 for(const f of l){const a=document.createElement('a');a.className='file card';a.href='/dl/'+f.id;a.download=f.name;
  const b=document.createElement('b');b.textContent=f.name;a.append(b,document.createElement('br'),
  Object.assign(document.createElement('small'),{textContent:h(f.size)}));box.append(a)}}catch(e){}}
setInterval(load,4000);load();
</script></body></html>"""


# ---------- request handler ----------
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "QuickDrop"

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="text/plain", extra=()):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8" if ctype.startswith("text") else ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "qd" and v and sess_hash(v) in STATE["sessions"]:
                STATE["seen"] = time.time()
                return True
        return False

    def _claim(self, token):
        """A phone presenting the one-time QR token is paired (after laptop approval)."""
        with STATE["lock"]:
            if not secrets.compare_digest(token.encode(), STATE["token"].encode()):
                return None
            who = self.client_address[0]
            if STATE["confirm"]:
                if STATE.get("ask"):
                    ok = STATE["ask"](who)
                else:
                    ok = input(f"\nDevice {who} wants to connect. Allow? [Y/n] ").strip().lower() not in ("n", "no")
                if not ok:
                    STATE["token"] = secrets.token_urlsafe(16)
                    return None
            cookie = secrets.token_urlsafe(32)
            STATE["sessions"].add(sess_hash(cookie))
            save_sessions()
            STATE["token"] = secrets.token_urlsafe(16)   # QR is single use
            STATE["seen"] = time.time()
            print(f"[+] Phone {who} paired.")
            return cookie

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/api/ping":
            return self._send(200, "quickdrop")
        if u.path == "/c" and "t" in q:
            c = self._claim(q["t"][0])
            if not c:
                return self._send(403, "Invalid or already used QR code. Use the newest QR code on the laptop.")
            return self._send(303, b"", extra=[("Location", "/"),
                              ("Set-Cookie", f"qd={c}; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age=31536000")])
        if not self._authed():
            return self._send(401, "Not authorised. Scan the QR code shown on the laptop.")
        if u.path == "/":
            return self._send(200, PAGE, "text/html")
        if u.path == "/api/files":
            fs = [{"id": i, "name": p.name, "size": p.stat().st_size} for i, p in shared_files().items()]
            return self._send(200, json.dumps(fs), "application/json")
        if u.path.startswith("/dl/"):
            p = shared_files().get(u.path[4:])
            if not p:
                return self._send(404, "Not found")
            return self._download(p)
        self._send(404, "Not found")

    def _download(self, p):
        try:
            size = p.stat().st_size
        except OSError:
            return self._send(404, "Not found")
        start, end, code = 0, size - 1, 200
        r = self.headers.get("Range", "")
        if r.startswith("bytes="):
            a, _, b = r[6:].partition("-")
            try:
                start = int(a) if a else max(0, size - int(b))
                end = int(b) if (a and b) else size - 1
                code = 206
            except ValueError:
                start, end, code = 0, size - 1, 200
        end = min(end, size - 1)
        self.send_response(code)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(p.name))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with open(p, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                b = f.read(min(CHUNK, left))
                if not b:
                    break
                self.wfile.write(b)
                left -= len(b)
        print(f"[->] Sent {p.name} ({human(end - start + 1)})")

    def do_POST(self):
        if not self._authed():
            return self._send(401, "Not authorised")
        if self.path != "/up":
            return self._send(404, "Not found")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._send(411, "Length required")
        name = safe_name(self.headers.get("X-Filename"))
        STATE["recv"].mkdir(parents=True, exist_ok=True)
        dest = unique_path(STATE["recv"], name)
        part = dest.with_name(dest.name + ".part")
        h, left = hashlib.sha256(), length
        try:
            with open(part, "wb") as f:
                while left > 0:
                    b = self.rfile.read(min(CHUNK, left))
                    if not b:
                        raise ConnectionError("interrupted")
                    h.update(b)
                    f.write(b)
                    left -= len(b)
            part.rename(dest)
        except Exception:
            try:
                part.unlink()
            except OSError:
                pass
            self.close_connection = True
            return
        print(f"[<-] Received {dest.name} ({human(length)})  sha256={h.hexdigest()[:16]}...")
        cb = STATE.get("on_received")
        if cb:
            cb(dest)
        self._send(200, json.dumps({"name": dest.name, "sha256": h.hexdigest()}), "application/json")


def start_server(port):
    load_sessions()
    ip = local_ip()
    cert, key, fp = ensure_cert(ip)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(cert, key)
    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    srv.daemon_threads = True
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    return srv, ip, fp


def main():
    ap = argparse.ArgumentParser(description="QuickDrop secure file transfer")
    ap.add_argument("--port", type=int, default=8443)
    ap.add_argument("--recv", default="received", help="folder for files from phone")
    ap.add_argument("--share", default="share", help="folder of files offered to phone")
    ap.add_argument("--no-confirm", action="store_true", help="skip laptop approval prompt")
    a = ap.parse_args()
    STATE.update(recv=Path(a.recv), share=Path(a.share), confirm=not a.no_confirm)
    STATE["recv"].mkdir(exist_ok=True)
    STATE["share"].mkdir(exist_ok=True)
    srv, ip, fp = start_server(a.port)
    url = f"https://{ip}:{a.port}/c?t={STATE['token']}&fp={fp}"
    print("\n=== QuickDrop ===")
    print(f"Laptop IP : {ip}   (laptop must be connected to the phone hotspot)")
    print(f"Receive   : {STATE['recv'].resolve()}")
    print(f"Share     : {STATE['share'].resolve()}  (put files here to send to phone)\n")
    try:
        import qrcode
        q = qrcode.QRCode(border=1)
        q.add_data(url)
        q.print_ascii(invert=True)
    except ImportError:
        print("(pip install qrcode for a QR code)")
    print(f"\nScan the QR with the QuickDrop app, or open:\n{url}\nCtrl+C to stop.\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
