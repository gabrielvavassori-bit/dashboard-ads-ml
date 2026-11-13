"""HTTP delivery contract for the large individual and consolidated pages."""

import gzip
import io
import unittest
from unittest.mock import patch

import app


class _Handler:
    def __init__(self, accept_encoding="", path="/online"):
        self.path = path
        self.headers = {"Accept-Encoding": accept_encoding}
        self.wfile = io.BytesIO()
        self.response_headers = {}
        self.status = None

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.response_headers[name] = value

    def end_headers(self):
        pass


class HtmlCompressionTest(unittest.TestCase):
    def _send(self, accept_encoding, html, path="/online"):
        handler = _Handler(accept_encoding, path)
        with patch.object(app, "_inject_admin_impersonation_banner", lambda _handler, page: page):
            app._send_html(handler, html)
        self.assertEqual(handler.status, 200)
        self.assertEqual(int(handler.response_headers["Content-Length"]), len(handler.wfile.getvalue()))
        self.assertEqual(handler.response_headers["Vary"], "Accept-Encoding")
        self.assertEqual(handler.response_headers["Cache-Control"], "no-store, no-cache, must-revalidate, max-age=0")
        return handler

    def test_large_individual_and_consolidated_pages_use_gzip_when_accepted(self):
        html = "<html>ação " + ("produto-12345 " * 9000) + "</html>"
        for path in ("/online?confirmed=1", "/online/consolidado"):
            with self.subTest(path=path):
                handler = self._send("br, gzip;q=1.0", html, path)
                self.assertEqual(handler.response_headers["Content-Encoding"], "gzip")
                self.assertEqual(gzip.decompress(handler.wfile.getvalue()), html.encode("utf-8"))
                self.assertLess(len(handler.wfile.getvalue()), len(html.encode("utf-8")))

    def test_gzip_opt_out_and_unsupported_clients_get_original_html(self):
        html = "<html>ação " + ("produto-12345 " * 9000) + "</html>"
        for encoding in ("", "gzip;q=0", "br"):
            with self.subTest(encoding=encoding):
                handler = self._send(encoding, html)
                self.assertNotIn("Content-Encoding", handler.response_headers)
                self.assertEqual(handler.wfile.getvalue(), html.encode("utf-8"))

    def test_small_html_is_not_compressed(self):
        handler = self._send("gzip", "<html>ok</html>")
        self.assertNotIn("Content-Encoding", handler.response_headers)
        self.assertEqual(handler.wfile.getvalue(), b"<html>ok</html>")


if __name__ == "__main__":
    unittest.main()
