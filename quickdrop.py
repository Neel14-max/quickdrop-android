#!/usr/bin/env python3
"""
QuickDrop - fast, private phone <-> laptop file transfer over your hotspot.

Run on the laptop:   python quickdrop.py
Scan the QR code with the phone camera -> opens in the phone browser.

Security: HTTPS (TLS) encryption, one-time QR token, session cookie,
laptop-side approval of the device, SHA-256 of every received file.
No cloud, no internet needed, no mobile data used.
"""
import argparse, datetime, hashlib, ipaddress, json, os, secrets, socket, ssl
import sys, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CHUNK = 1024 * 1024  # 1 MB raw binary chunks
HOME = Path.home() / ".quickdrop"
STATE = {"token": secrets.token_urlsafe(16), "session": None, "lock": threading.Lock(),
         "confirm": True, "recv": Path("received"), "share": Path("share")}


# ---------- network / TLS helpers ----------
def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent
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
                .not_valid_after(now + datetime.timedelta(days=365))
                .add_extension(x509.SubjectAlternativeName(
                    [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address(ip))]), False)
                .sign(key, hashes.SHA256()))
        cp.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        kp.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                         serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
        os.chmod(kp, 0o600)
    der = ssl.PEM_cert_to_DER_cert(cp.read_text())
    return cp, kp, hashlib.sha256(der).hexdigest()


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


# ---------- web page ----------
PAGE = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>QuickDrop</title><style>
:root{color-scheme:light dark;--b:#2563eb}
body{font-family:system-ui,sans-serif;max-width:560px;margin:0 auto;padding:16px}
h1{font-size:22px}h2{font-size:16px;margin-top:28px}
.btn{display:block;width:100%;padding:16px;border:0;border-radius:12px;background:var(--b);
color:#fff;font-size:17px;text-align:center;box-sizing:border-box}
.card{border:1px solid #8884;border-radius:12px;padding:10px 12px;margin:8px 0;font-size:14px;word-break:break-all}
.bar{height:6px;background:#8883;border-radius:3px;margin-top:6px}.bar i{display:block;height:6px;background:var(--b);border-radius:3px;width:0}
a{color:var(--b)}small{opacity:.7}
</style></head><body>
<h1>QuickDrop</h1><small>Encrypted direct transfer. Nothing leaves your hotspot.</small>
<h2>Phone &rarr; Laptop</h2>
<label class=btn>Choose files to send<input id=f type=file multiple hidden></label>
<div id=up></div>
<h2>Laptop &rarr; Phone</h2><div id=dl><small>Loading...</small></div>
<button class=btn style="background:#555;margin-top:10px" onclick=load()>Refresh list</button>
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
 x.onload=()=>{let m='Failed ('+x.status+')';
  if(x.status==200){const j=JSON.parse(x.responseText);m='Done - saved. SHA-256 '+j.sha256.slice(0,16)+'...'}
  d.querySelector('span').textContent=m;r()};
 x.onerror=()=>{d.querySelector('span').textContent='Connection error';r()};
 x.send(f)})}
async function load(){const r=await fetch('/api/files');const l=await r.json();
 $('dl').innerHTML=l.length?'':'<small>Put files in the laptop "share" folder, then refresh.</small>';
 for(const f of l){const d=document.createElement('div');d.className='card';
  const a=document.createElement('a');a.href='/dl/'+encodeURIComponent(f.name);a.download=f.name;
  a.textContent=f.name;d.append(a,document.createElement('br'));
  d.append(Object.assign(document.createElement('small'),{textContent:h(f.size)}));$('dl').append(d)}}
load();
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
        s = STATE["session"]
        if not s:
            return False
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "qd" and secrets.compare_digest(v, s):
                return True
        return False

    def _claim(self, token):
        """First device that presents the one-time QR token becomes the session."""
        with STATE["lock"]:
            if STATE["session"] or not secrets.compare_digest(token, STATE["token"]):
                return None
            who = self.client_address[0]
            if STATE["confirm"]:
                ans = input(f"\nDevice {who} wants to connect. Allow? [Y/n] ").strip().lower()
                if ans in ("n", "no"):
                    STATE["token"] = secrets.token_urlsafe(16)
                    return None
            STATE["session"] = secrets.token_urlsafe(32)
            print(f"[+] Device {who} connected.")
            return STATE["session"]

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/c" and "t" in q:
            s = self._claim(q["t"][0])
            if not s:
                return self._send(403, "Invalid or already used link. Restart QuickDrop for a new QR code.")
            return self._send(303, b"", extra=[("Location", "/"),
                              ("Set-Cookie", f"qd={s}; Secure; HttpOnly; SameSite=Strict; Path=/")])
        if not self._authed():
            return self._send(401, "Not authorised. Scan the QR code shown on the laptop.")
        if u.path == "/":
            return self._send(200, PAGE, "text/html")
        if u.path == "/api/files":
            fs = [{"name": p.name, "size": p.stat().st_size}
                  for p in sorted(STATE["share"].iterdir()) if p.is_file()]
            return self._send(200, json.dumps(fs), "application/json")
        if u.path.startswith("/dl/"):
            return self._download(safe_name(u.path[4:]))
        self._send(404, "Not found")

    def _download(self, name):
        p = STATE["share"] / name
        if not p.is_file():
            return self._send(404, "Not found")
        size, start, end, code = p.stat().st_size, 0, p.stat().st_size - 1, 200
        r = self.headers.get("Range", "")
        if r.startswith("bytes="):  # resume support
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
        self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(name))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with open(p, "rb") as f:  # streamed from disk, never fully in RAM
            f.seek(start)
            left = end - start + 1
            while left > 0:
                b = f.read(min(CHUNK, left))
                if not b:
                    break
                self.wfile.write(b)
                left -= len(b)
        print(f"[->] Sent {name} ({human(end - start + 1)})")

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
        STATE["recv"].mkdir(exist_ok=True)
        dest = unique_path(STATE["recv"], name)
        part = dest.with_name(dest.name + ".part")
        h, left = hashlib.sha256(), length
        try:
            with open(part, "wb") as f:  # streamed straight to disk
                while left > 0:
                    b = self.rfile.read(min(CHUNK, left))
                    if not b:
                        raise ConnectionError("interrupted")
                    h.update(b)
                    f.write(b)
                    left -= len(b)
            part.rename(dest)
        except Exception:
            part.unlink(missing_ok=True)
            self.close_connection = True
            return
        print(f"[<-] Received {dest.name} ({human(length)})  sha256={h.hexdigest()[:16]}...")
        self._send(200, json.dumps({"name": dest.name, "sha256": h.hexdigest()}), "application/json")


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

    ip = local_ip()
    cert, key, fp = ensure_cert(ip)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(cert, key)
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), H)
    srv.daemon_threads = True
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)

    url = f"https://{ip}:{a.port}/c?t={STATE['token']}&fp={fp}"
    print("\n=== QuickDrop ===")
    print(f"Laptop IP : {ip}   (laptop must be connected to the phone hotspot)")
    print(f"Receive   : {STATE['recv'].resolve()}")
    print(f"Share     : {STATE['share'].resolve()}  (put files here to send to phone)")
    print(f"Cert SHA-256: {fp[:32]}...\n")
    try:
        import qrcode
        q = qrcode.QRCode(border=1)
        q.add_data(url)
        q.print_ascii(invert=True)
    except ImportError:
        print("(pip install qrcode for a QR code)")
    print(f"\nScan the QR with the phone camera, or open:\n{url}\n")
    print("Using the QuickDrop app: no warning. Using a browser instead: tap 'Advanced' -> 'Proceed' once.")
    print("Press Ctrl+C to stop.\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
