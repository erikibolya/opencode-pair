"""Render a static, self-contained demo of the page for GitHub Pages.

The demo shows made-up data: the pairing code is fake and the server address is
``opencode.example.com``, so the QR codes in it are not redeemable anywhere.
"""

import os
import pathlib
import sys


def main() -> None:
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "_site")
    out.mkdir(parents=True, exist_ok=True)

    os.environ["OPENCODE_PUBLIC_URL"] = "https://opencode.example.com"
    os.environ["OPENCODE_PASSWORD"] = "demo-password-123"
    os.environ["PAGE_TITLE"] = "OpenCode - párování (ukázka)"

    root = pathlib.Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root / "app"))

    # imported after the environment is set up on purpose
    import main as app

    page = app.build_page(app.PUBLIC_URL, "DEMO-CODE-123456", 300)
    banner = (
        '<div class="badge" style="margin-bottom:10px">statická ukázka &ndash; '
        "kód i adresa serveru jsou vymyšlené</div>"
    )
    page = page.replace("<h1>", banner + "<h1>", 1)

    (out / "index.html").write_text(page, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"wrote {out / 'index.html'} ({len(page)} bytes)")


if __name__ == "__main__":
    main()
