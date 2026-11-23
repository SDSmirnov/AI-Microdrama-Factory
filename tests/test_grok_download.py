"""A failed Grok clip download must raise and leave no partial file behind."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.animation import grok


class _Resp:
    def __init__(self, status, content):
        self.status_code, self.content = status, content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error")


class DownloadTests(unittest.TestCase):
    def test_bad_download_writes_nothing(self):
        cases = [(_Resp(403, b'<html>denied</html>'), requests.HTTPError),
                 (_Resp(200, b''), RuntimeError)]
        with tempfile.TemporaryDirectory() as tmp:
            for resp, error in cases:
                with self.subTest(status=resp.status_code, error=error.__name__):
                    out = Path(tmp) / f'clip-{resp.status_code}.mp4'
                    with mock.patch.object(grok.requests, 'get', lambda url, timeout: resp):
                        with self.assertRaises(error):
                            grok._download('https://cdn/x.mp4', out)
                    self.assertFalse(out.exists())

    def test_good_download_is_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'clip.mp4'
            with mock.patch.object(grok.requests, 'get',
                                   lambda url, timeout: _Resp(200, b'mp4')):
                grok._download('https://cdn/x.mp4', out)
            self.assertEqual(out.read_bytes(), b'mp4')


if __name__ == '__main__':
    unittest.main()
