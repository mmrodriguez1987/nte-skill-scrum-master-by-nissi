"""Offline transport tests; no real credentials or network requests."""

import base64
import io
from http.client import IncompleteRead
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import tracker_api as api


class Response:
    status = 200

    def __init__(self, data):
        self.data = json.dumps(data).encode()
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return self.data


class TrackerTests(unittest.TestCase):
    def test_dotenv_is_data_and_selected_file_is_authoritative(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / ".env"
            file.write_text("# comment\nJIRA_PAT='$(do-not-execute)'\nSCRUM_PROVIDER=jira-dc\n")
            with patch.dict(api.os.environ, {"SCRUM_PROVIDER": "jira-cloud"}, clear=True):
                env = api.load_env(file)
            self.assertEqual(env["JIRA_PAT"], "$(do-not-execute)")
            self.assertEqual(env["SCRUM_PROVIDER"], "jira-dc")

    def test_missing_file_does_not_fall_back_to_environment(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(api.os.environ, {"JIRA_PAT": "fake"}):
            with self.assertRaises(api.SafeError):
                api.load_env(Path(folder) / "missing.env")

    def test_environment_only_configuration_is_explicit(self):
        with patch.dict(api.os.environ, {"JIRA_PAT": "fake"}, clear=True):
            self.assertEqual(api.load_env(None), {"JIRA_PAT": "fake"})

    def test_bad_dotenv_does_not_echo_value(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / ".env"
            file.write_text("BAD KEY=private-value")
            with self.assertRaises(api.SafeError) as error:
                api.load_env(file)
            self.assertNotIn("private-value", str(error.exception))

    def test_authentication_modes(self):
        for provider, extra, expected in [
            ("jira-cloud", {"JIRA_EMAIL": "a@example.test", "JIRA_API_TOKEN": "fake-secret"},
             "Basic " + base64.b64encode(b"a@example.test:fake-secret").decode()),
            ("jira-dc", {"JIRA_PAT": "fake-secret"}, "Bearer fake-secret"),
            ("azure-devops", {"AZURE_DEVOPS_PAT": "fake-secret"},
             "Basic " + base64.b64encode(b":fake-secret").decode()),
            ("azure-devops", {"AZURE_DEVOPS_AUTH_MODE": "access-token",
                              "AZURE_DEVOPS_ACCESS_TOKEN": "fake-secret"}, "Bearer fake-secret"),
        ]:
            with self.subTest(provider=provider):
                env = {"SCRUM_PROVIDER": provider,
                       "JIRA_BASE_URL": "https://example.test/jira",
                       "AZURE_DEVOPS_URL": "https://dev.azure.com/org", **extra}
                self.assertEqual(api.configuration(env)[2], expected)

    def test_git_pat_is_independent_from_tracker_auth(self):
        env = {"GIT_PROVIDER": "github", "GIT_API_URL": "https://api.github.com",
               "GIT_PAT": "git-fake", "AZURE_DEVOPS_PAT": "tracker-fake"}
        self.assertEqual(api.configuration(env, "git")[2], "Bearer git-fake")
        env["GIT_PROVIDER"] = "azure-repos"
        self.assertEqual(api.configuration(env, "git")[2],
                         "Basic " + base64.b64encode(b":git-fake").decode())

    def test_reject_unsafe_bases(self):
        for base in ["http://example.test", "https://user:pass@example.test",
                     "https://example.test?token=x", "https://example.test/#frag"]:
            with self.subTest(base=base), self.assertRaises(api.SafeError):
                api.configuration({"SCRUM_PROVIDER": "jira-dc", "JIRA_PAT": "fake",
                                   "JIRA_BASE_URL": base})

    def test_context_is_preserved_and_escapes_rejected(self):
        base = "https://example.test/jira"
        self.assertEqual(api.destination(base, "/rest/api/2/myself"),
                         base + "/rest/api/2/myself")
        for path in ["https://other.test", "//other.test/api", "/../x",
                     "/%2e%2e/x", "/%252e%252e/x", "/x\\y", "/x#frag", "/x\ny"]:
            with self.subTest(path=path), self.assertRaises(api.SafeError):
                api.destination(base, path)

    @patch("tracker_api.build_opener")
    def test_writes_require_deliberate_flag(self, opener):
        with self.assertRaises(api.SafeError):
            api.perform("https://example.test", "Bearer fake", "fake", "/api", "POST")
        opener.assert_not_called()

    @patch("tracker_api.build_opener")
    def test_request_and_response_do_not_expose_auth(self, opener):
        opener.return_value.open.return_value = Response(
            {"id": "APP-1", "token": "unrelated", "body": "contains fake-secret"})
        result = api.perform("https://example.test", "Bearer fake-secret", "fake-secret", "/api")
        req = opener.return_value.open.call_args.args[0]
        self.assertEqual(req.get_header("Authorization"), "Bearer fake-secret")
        self.assertEqual(result["data"]["id"], "APP-1")
        self.assertNotIn("fake-secret", json.dumps(result))
        self.assertEqual(result["data"]["token"], "[REDACTED]")

    @patch("tracker_api.build_opener")
    def test_json_patch_is_sent_with_correct_type(self, opener):
        opener.return_value.open.return_value = Response({"id": 7})
        body = b'[{"op":"add","path":"/fields/System.Title","value":"Test"}]'
        api.perform("https://example.test", "Basic abc", "fake-secret", "/api", "PATCH",
                    body, "application/json-patch+json", True)
        req = opener.return_value.open.call_args.args[0]
        self.assertEqual(req.data, body)
        self.assertEqual(req.get_header("Content-type"), "application/json-patch+json")

    @patch("tracker_api.build_opener")
    def test_errors_are_sanitized_and_never_retried(self, opener):
        errors = [HTTPError("https://example.test", 401, "private-value", {}, io.BytesIO(b"secret")),
                  HTTPError("https://example.test", 302, "redirect", {}, None),
                  URLError("private-value")]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                opener.reset_mock()
                opener.return_value.open.side_effect = error
                with self.assertRaises(api.SafeError) as raised:
                    api.perform("https://example.test", "Bearer fake", "fake", "/api",
                                "POST", b"{}", allow_write=True)
                self.assertNotIn("private-value", str(raised.exception))
                self.assertEqual(opener.return_value.open.call_count, 1)

    def test_redirects_are_not_followed(self):
        self.assertIsNone(api.NoRedirect().redirect_request(None, None, 302, "", {},
                                                           "https://other.test"))

    @patch("tracker_api.build_opener")
    def test_cursor_survives_across_two_jira_pages(self, opener):
        opener.return_value.open.side_effect = [
            Response({"issues": [{"id": "1"}], "nextPageToken": "page-2", "isLast": False}),
            Response({"issues": [{"id": "2"}], "isLast": True})]
        first = api.perform("https://example.test", "Bearer fake-secret", "fake-secret", "/search/jql")
        cursor = first["data"]["nextPageToken"]
        second = api.perform("https://example.test", "Bearer fake-secret", "fake-secret",
                             "/search/jql?nextPageToken=" + cursor)
        self.assertEqual(cursor, "page-2")
        self.assertEqual(second["data"]["issues"][0]["id"], "2")

    @patch("tracker_api.build_opener")
    def test_operational_headers_survive_without_auth_headers(self, opener):
        response = Response({"value": []})
        response.headers = {"X-MS-ContinuationToken": "page-2", "Set-Cookie": "private"}
        opener.return_value.open.return_value = response
        result = api.perform("https://example.test", "Bearer fake-secret", "fake-secret", "/api")
        self.assertEqual(result["headers"], {"x-ms-continuationtoken": "page-2"})

    @patch("tracker_api.build_opener")
    def test_encoded_credentials_are_blocked_before_network(self, opener):
        payloads = [b'{"description":"\\u0066ake-secret"}',
                    b'{"\\u0066ake-secret":"value"}',
                    b'{"nested":["fake-secret"]}']
        for body in payloads:
            with self.subTest(body=body), self.assertRaises(api.SafeError):
                api.perform("https://example.test", "Bearer fake-secret", "fake-secret",
                            "/api", "POST", body, allow_write=True)
        with self.assertRaises(api.SafeError):
            api.perform("https://example.test", "Bearer fake-secret", "fake-secret",
                        "/api?value=%66ake-secret")
        opener.assert_not_called()

    @patch("tracker_api.build_opener")
    def test_validation_errors_are_useful_and_sanitized(self, opener):
        body = io.BytesIO(b'{"errors":{"assignee":"Not assignable: fake-secret"},"debug":"omit"}')
        opener.return_value.open.side_effect = HTTPError("https://example.test", 400, "bad", {}, body)
        with self.assertRaises(api.SafeError) as raised:
            api.perform("https://example.test", "Bearer fake-secret", "fake-secret", "/api")
        details = raised.exception.details
        self.assertIn("Not assignable", details["validation"])
        self.assertNotIn("fake-secret", json.dumps(details))
        self.assertNotIn("debug", details["validation"])

    @patch("tracker_api.build_opener")
    def test_rate_limit_retains_retry_metadata_without_retrying(self, opener):
        opener.return_value.open.side_effect = HTTPError("https://example.test", 429, "rate", {"Retry-After": "12"}, io.BytesIO(b'{}'))
        with self.assertRaises(api.SafeError) as raised:
            api.perform("https://example.test", "Bearer fake-secret", "fake-secret", "/api")
        self.assertEqual(raised.exception.details["headers"]["retry-after"], "12")
        self.assertEqual(opener.return_value.open.call_count, 1)

    @patch("tracker_api.build_opener")
    def test_truncated_successful_write_requires_reconciliation(self, opener):
        response = Response({})
        response.status = 201
        response.read = lambda: (_ for _ in ()).throw(IncompleteRead(b"private-partial-body", 100))
        opener.return_value.open.return_value = response
        with self.assertRaises(api.SafeError) as raised:
            api.perform("https://example.test", "Bearer fake-secret", "fake-secret", "/api",
                        "POST", b"{}", allow_write=True)
        self.assertEqual(raised.exception.details["outcome"], "unknown")
        self.assertTrue(raised.exception.details["reconcile_required"])
        self.assertNotIn("private-partial-body", str(raised.exception))
        self.assertEqual(opener.return_value.open.call_count, 1)

    @patch("tracker_api.build_opener")
    def test_truncated_get_is_a_structured_read_failure(self, opener):
        response = Response({})
        response.read = lambda: (_ for _ in ()).throw(IncompleteRead(b"private", 100))
        opener.return_value.open.return_value = response
        with self.assertRaises(api.SafeError) as raised:
            api.perform("https://example.test", "Bearer fake-secret", "fake-secret", "/api")
        self.assertEqual(raised.exception.details["outcome"], "read_failed")
        self.assertFalse(raised.exception.details["reconcile_required"])

    @patch("tracker_api.build_opener")
    def test_truncated_error_body_is_sanitized_and_closed(self, opener):
        error = HTTPError("https://example.test", 500, "failed", {}, io.BytesIO(b""))
        with patch.object(error, "read", side_effect=IncompleteRead(b"private", 100)), patch.object(error, "close", wraps=error.close) as close:
            opener.return_value.open.side_effect = error
            with self.assertRaises(api.SafeError) as raised:
                api.perform("https://example.test", "Bearer fake-secret", "fake-secret", "/api",
                            "POST", b"{}", allow_write=True)
            self.assertTrue(raised.exception.details["response_incomplete"])
            self.assertTrue(raised.exception.details["reconcile_required"])
            self.assertNotIn("private", json.dumps(raised.exception.details))
            close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
