"""S03 SEC-04: remote media fetching must never probe internal IPs or redirects.

All requests and DNS lookups are mocks. No real network or model calls.
"""
import socket
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
import main


PUBLIC_DNS = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
PRIVATE_DNS = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.7", 443))]


def fake_response(status=200, location=None, chunks=(b"ok",), length=None):
    response = MagicMock()
    response.status_code = status
    response.headers = {"content-type": "image/png"}
    if location is not None:
        response.headers["location"] = location
    if length is not None:
        response.headers["content-length"] = str(length)
    response.iter_content.return_value = iter(chunks)
    response.__enter__.return_value = response
    return response


class RemoteMediaSecurityTests(unittest.TestCase):
    def test_loopback_linklocal_and_private_ip_never_make_http_request(self):
        for url in (
            "http://127.0.0.1:80/admin",
            "http://169.254.169.254/latest/meta-data/",
            "http://192.168.1.1/debug",
            "http://10.1.2.3/secret",
            "http://[::1]/internal",
        ):
            with self.subTest(url=url), patch("main.requests.get") as request:
                with self.assertRaises(HTTPException) as caught:
                    main.fetch_remote_media_bytes(url)
                self.assertEqual(caught.exception.status_code, 400)
                request.assert_not_called()

    def test_public_hostname_resolving_to_private_is_rejected(self):
        with patch("main.socket.getaddrinfo", return_value=PRIVATE_DNS), \
             patch("main.requests.get") as request:
            with self.assertRaises(HTTPException) as caught:
                main.fetch_remote_media_bytes("https://untrusted.example/image.png")
            self.assertEqual(caught.exception.status_code, 400)
            request.assert_not_called()

    def test_redirect_to_private_target_rejected_before_second_fetch(self):
        redirect = fake_response(status=302, location="http://127.0.0.1/admin")
        with patch("main.socket.getaddrinfo", return_value=PUBLIC_DNS), \
             patch("main.requests.get", return_value=redirect) as request:
            with self.assertRaises(HTTPException):
                main.fetch_remote_media_bytes("https://cdn.example/a.png")
            self.assertEqual(request.call_count, 1)
            redirect.close.assert_called()

    def test_public_remote_media_still_downloads(self):
        response = fake_response(chunks=(b"a", b"bc"), length=3)
        with patch("main.socket.getaddrinfo", return_value=PUBLIC_DNS), \
             patch("main.requests.get", return_value=response) as request:
            data, content_type = main.fetch_remote_media_bytes("https://cdn.example/photo.png")
            self.assertEqual(data, b"abc")
            self.assertEqual(content_type, "image/png")
            self.assertFalse(request.call_args.kwargs.get("allow_redirects", True))

    def test_oversized_content_length_rejected_without_download(self):
        response = fake_response(chunks=(b"payload",), length=10000)
        with patch("main.socket.getaddrinfo", return_value=PUBLIC_DNS), \
             patch("main.requests.get", return_value=response):
            with self.assertRaises(HTTPException) as caught:
                main.fetch_remote_media_bytes("https://cdn.example/large.png", max_bytes=1024)
            self.assertEqual(caught.exception.status_code, 413)


if __name__ == "__main__":
    unittest.main()
