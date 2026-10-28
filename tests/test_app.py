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


class CodeCacheTests(unittest.TestCase):
    def setUp(self):
        main._current.update(code=None, expires_at=0.0)

    def test_reuses_code_until_it_gets_old(self):
        with mock.patch.object(main, "create_code", return_value=("AAA", 300)) as create:
            self.assertEqual(main.get_code()[0], "AAA")
            self.assertEqual(main.get_code()[0], "AAA")
            self.assertEqual(create.call_count, 1)

    def test_force_creates_new_code(self):
        with mock.patch.object(main, "create_code", side_effect=[("C1", 300), ("C2", 300)]) as create:
            self.assertEqual(main.get_code()[0], "C1")
            self.assertEqual(main.get_code()[0], "C1")
            self.assertEqual(main.get_code(force=True)[0], "C2")
            self.assertEqual(create.call_count, 2)

    def test_expired_code_is_replaced(self):
        with mock.patch.object(main, "create_code", return_value=("OLD", 5)):
            main.get_code()
            code, left = main.get_code()
            self.assertEqual(code, "OLD")
            self.assertLessEqual(left, 5)


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
