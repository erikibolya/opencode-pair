"""opencode-pair - a tiny web page that hands out OpenCode pairing QR codes.

The page asks a running OpenCode server for a one-time pairing code
(``POST /api/pair``), renders it as a QR code and shows it next to the
permanent server address and password, so a phone can be paired without
touching a terminal.
"""

from __future__ import annotations

import base64
import html
import json
import os
import signal
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol

import qrcode

API_URL = os.environ.get("OPENCODE_API", "http://opencode:4096").rstrip("/")
PUBLIC_URL = os.environ.get("OPENCODE_PUBLIC_URL", "").rstrip("/")
PASSWORD = os.environ.get("OPENCODE_PASSWORD", "")
USERNAME = os.environ.get("OPENCODE_USERNAME", "opencode")
PORT = int(os.environ.get("PORT", "8080"))
TITLE = os.environ.get("PAGE_TITLE", "OpenCode - párování")
HIDE_PASSWORD = os.environ.get("HIDE_PASSWORD", "").strip().lower() in {"1", "true", "yes", "on"}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    "Content-Security-Policy": (
        "default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
        "script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
}


def create_code() -> tuple[str, int]:
    """Ask the OpenCode server for a fresh one-time pairing code."""
    req = urllib.request.Request(API_URL + "/api/pair", method="POST")
    if PASSWORD:
        token = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
        req.add_header("Authorization", "Basic " + token)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.load(resp)
    return str(data["code"]), int(data.get("expires_in", 300))


def qr_svg(data: str) -> str:
    """Render ``data`` as a compact inline SVG QR code."""
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    size = len(matrix)
    path = "".join(f"M{x} {y}h1v1h-1z" for y, row in enumerate(matrix) for x, dark in enumerate(row) if dark)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        'shape-rendering="crispEdges" role="img" aria-label="QR code">'
        f'<rect width="{size}" height="{size}" fill="#fff"/>'
        f'<path d="{path}" fill="#000"/></svg>'
    )


PAGE = """<!doctype html>
<html lang="cs">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>{title}</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:24px 16px 48px; background:#0f1115; color:#e6e8eb;
         font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width: 880px; margin: 0 auto; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .muted {{ color:#8b94a3; font-size:13px; }}
  .card {{ background:#161a21; border:1px solid #232936; border-radius:14px; padding:20px; margin-top:18px; }}
  .row {{ display:flex; gap:24px; flex-wrap:wrap; align-items:flex-start; }}
  .qr {{ background:#fff; border-radius:12px; padding:12px; width:280px; height:280px; flex:0 0 auto; }}
  .qr svg {{ width:100%; height:100%; display:block; }}
  .qr.small {{ width:160px; height:160px; }}
  .grow {{ flex:1 1 320px; min-width: 260px; }}
  .val {{ display:flex; gap:8px; align-items:center; margin:8px 0 14px; }}
  code {{ background:#0b0e13; border:1px solid #232936; border-radius:8px; padding:8px 10px;
          font:13px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace; word-break:break-all; flex:1; }}
  button {{ background:#2b3341; color:#e6e8eb; border:1px solid #39424f; border-radius:8px;
            padding:8px 12px; font:13px inherit; cursor:pointer; white-space:nowrap; }}
  button:hover {{ background:#39424f; }}
  button.primary {{ background:#3b6ef5; border-color:#3b6ef5; }}
  button.primary:hover {{ background:#4d7cf7; }}
  .timer {{ font-variant-numeric: tabular-nums; font-weight:600; }}
  .timer.low {{ color:#ffb454; }}
  .expired .timer {{ color:#ff6b6b; }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:999px; font-size:12px;
            background:#1f2632; border:1px solid #2b3341; color:#9aa4b2; }}
  .err {{ background:#2a1518; border:1px solid #5b2228; color:#ff9b9b; padding:12px;
          border-radius:10px; margin-top:14px; font-size:13px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>{title}</h1>
  <div class="muted">Server <code style="display:inline;padding:2px 6px">{public}</code></div>

  <div class="card">
    <div class="row">
      <div class="qr">{qr}</div>
      <div class="grow">
        <div class="badge">jednorázový login</div>
        <p class="muted" style="margin:10px 0 0">
          Naskenuj QR v aplikaci OpenCode. Odkaz je jednorázový a vyprší za
          <span class="timer" id="timer">{expires}</span>&nbsp;s.
        </p>
        <div class="val">
          <code id="link">{link}</code>
          <button onclick="copy('link', this)">Kopírovat</button>
        </div>
        <button class="primary" onclick="location.href='/new'">Nový kód</button>
      </div>
    </div>
    {error}
  </div>

  <div class="card">
    <div class="row">
      <div class="qr small">{qr_url}</div>
      <div class="grow">
        <div class="badge">trvalé přihlášení</div>
        <div class="muted" style="margin:10px 0 0">Adresa serveru</div>
        <div class="val">
          <code id="url">{public}</code>
          <button onclick="copy('url', this)">Kopírovat</button>
        </div>
        <div class="muted">Heslo</div>
        {password_row}
        <div class="muted">Basic auth user: <code style="display:inline;padding:2px 6px">{username}</code></div>
      </div>
    </div>
  </div>
</div>
<script>
  function copy(id, btn) {{
    var text = document.getElementById(id).textContent.trim();
    var done = function () {{
      var original = btn.textContent;
      btn.textContent = "Zkopírováno";
      setTimeout(function () {{ btn.textContent = original; }}, 1500);
    }};
    if (navigator.clipboard && window.isSecureContext) {{
      navigator.clipboard.writeText(text).then(done, function () {{ fallback(text, done); }});
    }} else {{ fallback(text, done); }}
  }}
  function fallback(text, done) {{
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try {{ document.execCommand("copy"); done(); }} catch (e) {{}}
    document.body.removeChild(ta);
  }}
  (function () {{
    var el = document.getElementById("timer");
    var left = {expires};
    setInterval(function () {{
      left -= 1;
      if (left <= 0) {{
        left = 0;
        el.textContent = "0";
        document.body.classList.add("expired");
        setTimeout(function () {{ location.reload(); }}, 2500);
        return;
      }}
      el.textContent = left;
      if (left <= 30) el.classList.add("low");
    }}, 1000);
  }})();
</script>
</body>
</html>
"""


def password_row() -> str:
    if HIDE_PASSWORD:
        return '<div class="val"><code id="pw">heslo je skryté (HIDE_PASSWORD)</code></div>'
    return (
        f'<div class="val"><code id="pw">{html.escape(PASSWORD)}</code>'
        "<button onclick=\"copy('pw', this)\">Kopírovat</button></div>"
    )


def build_page(public: str, code: str, expires: int, error: str = "") -> str:
    link = f"{public}/auth/connect/{code}" if code else ""
    return PAGE.format(
        title=html.escape(TITLE),
        public=html.escape(public),
        link=html.escape(link),
        qr=qr_svg(link) if link else qr_svg(public),
        qr_url=qr_svg(public),
        password_row=password_row(),
        username=html.escape(USERNAME),
        expires=expires,
        error=error,
    )


class HeadersLike(Protocol):
    """Anything carrying HTTP headers, so tests can pass a plain object."""

    headers: Any


def request_public_url(handler: HeadersLike) -> str:
    if PUBLIC_URL:
        return PUBLIC_URL
    proto = handler.headers.get("X-Forwarded-Proto", "http").split(",")[0].strip()
    host = handler.headers.get("X-Forwarded-Host") or handler.headers.get("Host") or "localhost"
    return f"{proto}://{host}"


class Handler(BaseHTTPRequestHandler):
    server_version = "opencode-pair"
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send(200, "text/plain; charset=utf-8", b"ok")
            return

        if self.path == "/robots.txt":
            self._send(200, "text/plain; charset=utf-8", b"User-agent: *\nDisallow: /\n")
            return

        if self.path.startswith("/new"):
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self._security_headers()
            self.end_headers()
            return

        if self.path not in ("/", "/index.html"):
            self._send(404, "text/plain; charset=utf-8", b"not found")
            return

        public = request_public_url(self)
        code = ""
        expires = 300
        error = ""
        try:
            code, expires = create_code()
        except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
            error = f'<div class="err">Nepodařilo se vytvořit párovací kód: {html.escape(str(exc))}</div>'
        self._send(200, "text/html; charset=utf-8", build_page(public, code, expires, error).encode())

    def _security_headers(self) -> None:
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}", flush=True)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(
        f"opencode-pair on :{PORT} (api={API_URL} public={PUBLIC_URL or 'auto'} hide_password={HIDE_PASSWORD})",
        flush=True,
    )

    def _shutdown(signum: int, frame: object) -> None:
        print("shutting down", flush=True)
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    server.serve_forever()


if __name__ == "__main__":
    main()
