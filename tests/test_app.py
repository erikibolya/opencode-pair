import http.client
import os
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import main


class FakeHandler:
    def __init__(self, headers):
        self.headers = headers


class QrTests(unittest.TestCase):
    def test_qr_svg_is_inline_svg(self):
        svg = main.qr_svg("https://example.com/auth/connect/abc")
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn('viewBox="0 0', svg)
        self.assertIn("<path", svg)
        self.assertNotIn("<?xml", svg)

    def test_qr_svg_has_no_whitespace_in_drawn_modules(self):
        small = main.qr_svg("a")
        large = main.qr_svg("https://example.com/" + "x" * 100)
        self.assertLess(len(small), len(large))


class PageTests(unittest.TestCase):
    def test_page_contains_link_and_credentials(self):
        page = main.build_page("https://pair.example.com", "CODE123", 300)
        self.assertIn("https://pair.example.com/auth/connect/CODE123", page)
        self.assertIn("https://pair.example.com", page)
        self.assertIn(main.PASSWORD, page)

    def test_page_can_hide_the_password(self):
        with (
            mock.patch.object(main, "PASSWORD", "super-secret"),
            mock.patch.object(main, "HIDE_PASSWORD", True),
        ):
            page = main.build_page("https://pair.example.com", "CODE123", 300)
        self.assertNotIn("super-secret", page)
        self.assertIn("HIDE_PASSWORD", page)

    def test_page_escapes_html(self):
        with mock.patch.object(main, "PASSWORD", "<script>alert(1)</script>"):
            page = main.build_page("https://pair.example.com", "CODE123", 300)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_page_survives_api_failure(self):
        page = main.build_page("https://pair.example.com", "", 300, '<div class="err">boom</div>')
        self.assertIn("boom", page)
        self.assertIn("https://pair.example.com", page)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.payload


class CreateCodeTests(unittest.TestCase):
    def _capture(self, payload=b'{"code":"C1","expires_in":300}'):
        captured = {}

        def fake_urlopen(req, timeout=0):
            captured["method"] = req.get_method()
            captured["url"] = req.full_url
            captured["auth"] = req.get_header("Authorization")
            return FakeResponse(payload)

        return captured, fake_urlopen

    def test_posts_with_basic_auth(self):
        captured, fake = self._capture()
        with (
            mock.patch.object(main, "PASSWORD", "secret"),
            mock.patch.object(main.urllib.request, "urlopen", fake),
        ):
            code, ttl = main.create_code()
        self.assertEqual((code, ttl), ("C1", 300))
        self.assertEqual(captured["method"], "POST")
        self.assertTrue(captured["url"].endswith("/api/pair"))
        self.assertTrue(captured["auth"].startswith("Basic "))

    def test_skips_auth_header_without_password(self):
        captured, fake = self._capture()
        with mock.patch.object(main, "PASSWORD", ""), mock.patch.object(main.urllib.request, "urlopen", fake):
            main.create_code()
        self.assertIsNone(captured["auth"])


class PublicUrlTests(unittest.TestCase):
    def test_explicit_public_url_wins(self):
        with mock.patch.object(main, "PUBLIC_URL", "https://pair.example.com"):
            self.assertEqual(
                main.request_public_url(FakeHandler({"Host": "internal:8080"})),
                "https://pair.example.com",
            )

    def test_derives_from_forwarded_headers(self):
        with mock.patch.object(main, "PUBLIC_URL", ""):
            url = main.request_public_url(
                FakeHandler(
                    {
                        "Host": "127.0.0.1:8080",
                        "X-Forwarded-Proto": "https",
                        "X-Forwarded-Host": "pair.example.com",
                    }
                )
            )
        self.assertEqual(url, "https://pair.example.com")


if __name__ == "__main__":
    unittest.main()


class HandlerTests(unittest.TestCase):
    server: ThreadingHTTPServer
    port: int
    thread: threading.Thread

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), main.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp, body

    def test_healthz(self):
        resp, body = self.get("/healthz")
        self.assertEqual(resp.status, 200)
        self.assertEqual(body, b"ok")

    def test_robots_blocks_crawlers(self):
        resp, body = self.get("/robots.txt")
        self.assertEqual(resp.status, 200)
        self.assertIn(b"Disallow: /", body)

    def test_security_headers(self):
        resp, _ = self.get("/healthz")
        self.assertEqual(resp.getheader("X-Frame-Options"), "DENY")
        self.assertEqual(resp.getheader("X-Content-Type-Options"), "nosniff")
        self.assertIn("default-src 'none'", resp.getheader("Content-Security-Policy"))
        self.assertIn("noindex", resp.getheader("X-Robots-Tag"))

    def test_unknown_path_is_404(self):
        resp, _ = self.get("/nope")
        self.assertEqual(resp.status, 404)

    def test_index_renders_pairing_link(self):
        with (
            mock.patch.object(main, "create_code", return_value=("CODE9", 300)),
            mock.patch.object(main, "PUBLIC_URL", "https://pair.example.com"),
        ):
            resp, body = self.get("/")
        self.assertEqual(resp.status, 200)
        self.assertIn(b"https://pair.example.com/auth/connect/CODE9", body)
        self.assertEqual(resp.getheader("Cache-Control"), "no-store")

    def test_api_failure_shows_error(self):
        with mock.patch.object(main, "create_code", side_effect=OSError("boom")):
            resp, body = self.get("/")
        self.assertEqual(resp.status, 200)
        self.assertIn(b"boom", body)

    def head(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("HEAD", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp, body

    def test_head_is_supported(self):
        resp, body = self.head("/healthz")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.getheader("Content-Length"), "2")
        self.assertEqual(body, b"")
        self.assertEqual(resp.getheader("X-Frame-Options"), "DENY")

    def test_new_redirects(self):
        resp, _ = self.get("/new")
        self.assertEqual(resp.status, 303)
        self.assertEqual(resp.getheader("Location"), "/")
