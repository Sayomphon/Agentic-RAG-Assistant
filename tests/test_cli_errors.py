"""Tests for the CLI's provider-failure contract.

What a failed run owes the caller: one actionable line on stderr, a
non-zero exit code, and nothing of the provider's raw payload — no
traceback, no request body, no credential. These tests fake the provider
errors, so they run offline.
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

import httpx
from openai import (
    APITimeoutError,
    AuthenticationError,
    InternalServerError,
    RateLimitError,
)

import main

_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
# The shape of a real provider body: enough to prove none of it is echoed.
_BODY = {"error": {"message": "The server had an error. secret-prompt-echo"}}


def _status_error(status: int, request_id: str = "") -> InternalServerError:
    headers = {"x-request-id": request_id} if request_id else {}
    response = httpx.Response(status, request=_REQUEST, headers=headers)
    return InternalServerError("server error", response=response, body=_BODY)


def _auth_error() -> AuthenticationError:
    response = httpx.Response(401, request=_REQUEST)
    return AuthenticationError("bad key", response=response, body=_BODY)


def _rate_limit_error() -> RateLimitError:
    response = httpx.Response(429, request=_REQUEST)
    return RateLimitError("slow down", response=response, body=_BODY)


def _graph_raising(exc: Exception) -> Mock:
    return Mock(invoke=Mock(side_effect=exc))


class ProviderMessageTests(unittest.TestCase):
    """Each failure mode gets its own message, and none leaks the payload."""

    def test_failure_modes_are_distinguishable(self) -> None:
        messages = {
            main.provider_error_message(_auth_error()),
            main.provider_error_message(_rate_limit_error()),
            main.provider_error_message(APITimeoutError(request=_REQUEST)),
            main.provider_error_message(_status_error(500)),
        }
        self.assertEqual(len(messages), 4)
        self.assertIn("OPENAI_API_KEY", main.provider_error_message(_auth_error()))

    def test_status_error_reports_code_and_request_id_only(self) -> None:
        message = main.provider_error_message(_status_error(500, "req_abc123"))
        self.assertIn("HTTP 500", message)
        self.assertIn("req_abc123", message)
        self.assertNotIn("secret-prompt-echo", message)

    def test_messages_stay_one_line(self) -> None:
        for exc in (_auth_error(), _rate_limit_error(), _status_error(503)):
            self.assertNotIn("\n", main.provider_error_message(exc))


class CliExitCodeTests(unittest.TestCase):
    """Single-query runs must be scriptable: exit code reflects the outcome."""

    def _run_cli(self, graph: Mock) -> tuple[int, str]:
        stderr = io.StringIO()
        with patch("main.build_graph", return_value=graph), patch(
            "main.require_api_key"
        ), patch.object(sys, "argv", ["main.py", "probation period"]):
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as caught:
                    main.main()
        return caught.exception.code, stderr.getvalue()

    def test_provider_failure_exits_non_zero_with_a_short_message(self) -> None:
        code, stderr = self._run_cli(_graph_raising(_status_error(500, "req_xyz")))

        self.assertEqual(code, 1)
        self.assertEqual(len(stderr.strip().splitlines()), 1)
        self.assertIn("HTTP 500", stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertNotIn("secret-prompt-echo", stderr)

    def test_answered_query_exits_zero(self) -> None:
        graph = Mock(
            invoke=Mock(
                return_value={
                    "query": "probation period",
                    "snippets": ["[Probation Period]\nSix months."],
                    "report": "Six months. [Probation Period]",
                    "route": "kb_query",
                    "search_attempts": ["probation period"],
                }
            )
        )

        code, stderr = self._run_cli(graph)

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")

    def test_debug_flag_re_raises_for_diagnosis(self) -> None:
        graph = _graph_raising(_status_error(500))
        with patch.dict("os.environ", {"AGENTIC_RAG_DEBUG": "1"}):
            with redirect_stdout(io.StringIO()):
                with self.assertRaises(InternalServerError):
                    main.run_query(graph, "probation period")


if __name__ == "__main__":
    unittest.main()
