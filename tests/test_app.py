import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import main  # noqa: E402


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
        with mock.patch.object(main, "PASSWORD", "secret"), mock.patch.object(
            main.urllib.request, "urlopen", fake
        ):
            code, ttl = main.create_code()
        self.assertEqual((code, ttl), ("C1", 300))
        self.assertEqual(captured["method"], "POST")
        self.assertTrue(captured["url"].endswith("/api/pair"))
        self.assertTrue(captured["auth"].startswith("Basic "))

    def test_skips_auth_header_without_password(self):
        captured, fake = self._capture()
        with mock.patch.object(main, "PASSWORD", ""), mock.patch.object(
            main.urllib.request, "urlopen", fake
        ):
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
                    {"Host": "127.0.0.1:8080", "X-Forwarded-Proto": "https", "X-Forwarded-Host": "pair.example.com"}
                )
            )
        self.assertEqual(url, "https://pair.example.com")


if __name__ == "__main__":
    unittest.main()
