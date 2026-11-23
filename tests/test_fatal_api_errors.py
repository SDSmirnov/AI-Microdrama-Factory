"""Account-level API failures stop the run instead of failing every later call."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.llm import base as base_mod
from lib.llm.base import retry_on_errors


def _raising(message):
    calls = []

    @retry_on_errors(max_retries=3, backoff_factor=0)
    def call():
        calls.append(1)
        raise RuntimeError(message)
    return call, calls


class FatalApiErrorTests(unittest.TestCase):
    def test_payment_required_and_bad_key_exit_without_retry(self):
        for message in ('402 Client Error: Payment Required for url: https://x',
                        '401 Client Error: Unauthorized for url: https://x',
                        '403 Client Error: Forbidden for url: https://x — '
                        '{"error":{"code":403,"message":"Key limit exceeded"}}'):
            call, calls = _raising(message)
            with self.assertRaises(SystemExit):
                call()
            self.assertEqual(len(calls), 1)

    def test_other_client_errors_stay_ordinary_exceptions(self):
        call, calls = _raising('403 Client Error: Forbidden for url: https://x — '
                               '{"error":{"code":403,"message":"Input was flagged"}}')
        with self.assertRaises(RuntimeError):
            call()
        self.assertEqual(len(calls), 1)


class _Resp:
    def __init__(self, status):
        self.status_code = status


def _http_error(status, body):
    import requests
    return requests.HTTPError(f"{status} Client Error — {body}", response=_Resp(status))


class StatusCodeTests(unittest.TestCase):
    def _calls(self, exc):
        calls = []

        @retry_on_errors(max_retries=3, backoff_factor=2)
        def call():
            calls.append(1)
            raise exc
        return call, calls

    def test_bad_request_mentioning_500_is_not_retried(self):
        call, calls = self._calls(_http_error(400, '{"message":"max_tokens must be <= 500"}'))
        with self.assertRaises(Exception):
            call()
        self.assertEqual(len(calls), 1)

    def test_status_503_is_retried(self):
        with mock.patch.object(base_mod.time, 'sleep') as sleep, \
                mock.patch.object(base_mod.random, 'uniform', return_value=0):
            call, calls = self._calls(_http_error(503, 'Service Unavailable'))
            with self.assertRaises(Exception):
                call()
        self.assertEqual(len(calls), 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [2, 4])

    def test_status_402_is_fatal(self):
        call, calls = self._calls(_http_error(402, 'Payment Required'))
        with self.assertRaises(SystemExit):
            call()
        self.assertEqual(len(calls), 1)


class ErrorBodyTests(unittest.TestCase):
    def test_openrouter_errors_carry_the_response_message(self):
        import requests
        from lib.llm.openrouter import _raise_with_body

        resp = requests.Response()
        resp.status_code, resp.url = 403, 'https://openrouter.ai/api/v1/chat/completions'
        resp._content = b'{"error":{"code":403,"message":"Key limit exceeded"}}'
        with self.assertRaises(requests.HTTPError) as ctx:
            _raise_with_body(resp)
        self.assertIn('Key limit exceeded', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
