#!/usr/bin/env python3
"""Small authenticated REST transport; secrets never become CLI arguments."""

import argparse
import base64
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class SafeError(Exception):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def load_env(path):
    if path is None:
        return dict(os.environ)
    if not path.is_file():
        raise SafeError("The selected .env file does not exist. Use --use-process-env for environment-only configuration.")
    values = {}
    if path.is_file():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not sep or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key):
                raise SafeError(f"Invalid .env format on line {number}.")
            if value.startswith(("'", '"')):
                if len(value) < 2 or value[-1] != value[0]:
                    raise SafeError(f"Invalid quoting on line {number}.")
                value = value[1:-1]
            values[key] = value
    # A selected project file is authoritative; never mix in another account.
    return values


def required(env, key):
    value = env.get(key, "").strip()
    if not value:
        raise SafeError(f"Missing configuration: {key}.")
    if any(ord(c) < 32 for c in value):
        raise SafeError(f"Invalid value for {key}.")
    return value


def configuration(env, service="tracker"):
    if service == "git":
        provider = required(env, "GIT_PROVIDER")
        base = required(env, "GIT_API_URL")
        secret = required(env, "GIT_PAT")
        if provider == "github":
            auth = "Bearer " + secret
        elif provider == "azure-repos":
            auth = "Basic " + base64.b64encode((":" + secret).encode()).decode()
        else:
            raise SafeError("GIT_PROVIDER must be github or azure-repos; other hosts require an adapter.")
        validate_base(base)
        return provider, base.rstrip("/"), auth, secret
    provider = required(env, "SCRUM_PROVIDER")
    if provider == "azure-devops":
        base = required(env, "AZURE_DEVOPS_URL")
        mode = env.get("AZURE_DEVOPS_AUTH_MODE", "pat")
        if mode == "pat":
            secret = required(env, "AZURE_DEVOPS_PAT")
            auth = "Basic " + base64.b64encode((":" + secret).encode()).decode()
        elif mode == "access-token":
            secret = required(env, "AZURE_DEVOPS_ACCESS_TOKEN")
            auth = "Bearer " + secret
        else:
            raise SafeError("AZURE_DEVOPS_AUTH_MODE must be pat or access-token.")
    elif provider == "jira-cloud":
        base = required(env, "JIRA_BASE_URL")
        secret = required(env, "JIRA_API_TOKEN")
        raw = required(env, "JIRA_EMAIL") + ":" + secret
        auth = "Basic " + base64.b64encode(raw.encode()).decode()
    elif provider == "jira-dc":
        base = required(env, "JIRA_BASE_URL")
        secret = required(env, "JIRA_PAT")
        auth = "Bearer " + secret
    else:
        raise SafeError("SCRUM_PROVIDER must be jira-cloud, jira-dc, or azure-devops.")
    validate_base(base)
    return provider, base.rstrip("/"), auth, secret


def validate_base(base):
    parts = urlsplit(base)
    if (parts.scheme != "https" or not parts.hostname or parts.username
            or parts.password or parts.query or parts.fragment
            or any(c.isspace() for c in base) or "\\" in base):
        raise SafeError("The base URL must use HTTPS and contain no credentials, query, or fragment.")


def destination(base, path):
    # Append under configured base (including organization/context), never urljoin.
    parts = urlsplit(path)
    decoded = path
    for _ in range(5):
        decoded_next = unquote(decoded)
        if decoded_next == decoded:
            break
        decoded = decoded_next
    if (not path.startswith("/") or path.startswith("//") or parts.scheme
            or parts.netloc or parts.fragment or "\\" in decoded
            or any(ord(c) < 32 or c.isspace() for c in path)
            or any(ord(c) < 32 for c in decoded)
            or any(p in ("..", ".") for p in decoded.split("?", 1)[0].split("/"))):
        raise SafeError("Use a path relative to the base URL, without an external destination or path traversal.")
    return base + path


SENSITIVE_KEYS = {"token", "password", "authorization", "secret", "pat",
                  "accesstoken", "refreshtoken", "apitoken", "clientsecret"}


def scrub(value, secrets):
    if isinstance(value, dict):
        return {
            scrub(k, secrets): "[REDACTED]" if re.sub(r"[-_]", "", k).lower() in SENSITIVE_KEYS
            else scrub(v, secrets) for k, v in value.items()
        }
    if isinstance(value, list):
        return [scrub(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
    return value


def assert_no_secrets(value, secrets):
    if isinstance(value, dict):
        for key, item in value.items():
            assert_no_secrets(key, secrets)
            assert_no_secrets(item, secrets)
    elif isinstance(value, list):
        for item in value:
            assert_no_secrets(item, secrets)
    elif isinstance(value, str) and any(secret and secret in value for secret in secrets):
        raise SafeError("The request contains credentials; remove the secrets.")


def operational_headers(headers, secrets):
    allowed = {"x-ms-continuationtoken", "retry-after", "x-ratelimit-reset",
               "x-request-id", "x-ms-request-id", "link"}
    return {key.lower(): scrub(value, secrets) for key, value in (headers or {}).items()
            if key.lower() in allowed}


def error_details(exc, secrets):
    details = {"status": exc.code, "headers": operational_headers(exc.headers, secrets)}
    try:
        data = json.loads(exc.read(16384))
        if isinstance(data, dict):
            allowed = {"message", "errorMessages", "errors", "typeKey", "errorCode"}
            safe = scrub({key: value for key, value in data.items() if key in allowed}, secrets)
            # Redact before bounding output, so truncation cannot expose a prefix.
            details["validation"] = json.dumps(safe, ensure_ascii=False)[:4000]
    except HTTPException:
        details["response_incomplete"] = True
    except (ValueError, UnicodeError, OSError, AttributeError):
        pass
    return details


def perform(base, auth, secret, path, method="GET", body=None,
            content_type="application/json", allow_write=False, extra_secrets=()):
    if method != "GET" and not allow_write:
        raise SafeError("This method requires --allow-write and an authorized scope.")
    url = destination(base, path)
    secrets = sorted(set([secret, auth, auth.split(" ", 1)[-1], *extra_secrets]),
                     key=len, reverse=True)
    decoded_url = url
    for _ in range(5):
        decoded_url = unquote(decoded_url)
    assert_no_secrets(decoded_url, secrets)
    if body is not None:
        assert_no_secrets(json.loads(body), secrets)
    headers = {"Authorization": auth, "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = content_type
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with build_opener(NoRedirect()).open(req, timeout=30) as response:
            raw = response.read()
            data = json.loads(raw) if raw else None
            return {"status": response.status,
                    "headers": operational_headers(getattr(response, "headers", None), secrets),
                    "data": scrub(data, secrets)}
    except HTTPError as exc:
        try:
            if exc.code in (301, 302, 303, 307, 308):
                raise SafeError("Redirect rejected; check the configured base URL.") from None
            details = error_details(exc, secrets)
            details["outcome"] = "unknown" if method != "GET" else "read_failed"
            details["reconcile_required"] = method != "GET"
            raise SafeError(f"HTTP {exc.code}. Check sanitized validation details and retry metadata.",
                            details) from None
        finally:
            exc.close()
    except (URLError, TimeoutError, OSError, HTTPException):
        raise SafeError("Network/TLS error, truncated response, or timeout. Reconcile writes before retrying.",
                        {"outcome": "unknown" if method != "GET" else "read_failed",
                         "reconcile_required": method != "GET"}) from None
    except (ValueError, UnicodeError):
        raise SafeError("The response is not valid JSON. Reconcile any write before retrying.",
                        {"outcome": "unknown" if method != "GET" else "read_failed",
                         "reconcile_required": method != "GET"}) from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--env-file", type=Path)
    source.add_argument("--use-process-env", action="store_true")
    parser.add_argument("--service", choices=["tracker", "git"], default="tracker")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    request = sub.add_parser("request")
    request.add_argument("--path", required=True)
    request.add_argument("--method", choices=["GET", "POST", "PUT", "PATCH"], default="GET")
    request.add_argument("--body-file", type=Path)
    request.add_argument("--content-type", choices=["application/json", "application/json-patch+json"], default="application/json")
    request.add_argument("--allow-write", action="store_true")
    args = parser.parse_args()
    try:
        env = load_env(None if args.use_process_env else (args.env_file or Path(".env")))
        provider, base, auth, secret = configuration(env, args.service)
        extra_secrets = [value for key, value in env.items()
                         if key.endswith(("_PAT", "_TOKEN", "_SECRET")) and value]
        if args.command == "check":
            if provider == "github":
                path = "/user"
            elif provider == "azure-repos":
                path = "/_apis/connectionData"
            elif provider == "azure-devops":
                project = quote(required(env, "AZURE_DEVOPS_PROJECT"), safe="")
                version = quote(env.get("AZURE_DEVOPS_API_VERSION", "7.1"), safe="")
                path = f"/{project}/_apis/wit/workitemtypes?api-version={version}"
            else:
                path = "/rest/api/3/myself" if provider == "jira-cloud" else "/rest/api/2/myself"
            result = perform(base, auth, secret, path, extra_secrets=extra_secrets)
            # Check proves access only to this read endpoint, not write permission.
            print(json.dumps({"status": result["status"], "provider": provider,
                              "read_check": "ok", "write_access": "not_checked"}))
        else:
            body = None
            if args.body_file:
                if args.method == "GET":
                    raise SafeError("GET does not support --body-file.")
                body = args.body_file.read_bytes()
            result = perform(base, auth, secret, args.path, args.method, body,
                             args.content_type, args.allow_write, extra_secrets)
            print(json.dumps(result, ensure_ascii=False))
        return 0
    except SafeError as exc:
        print(json.dumps({"error": str(exc), **exc.details}, ensure_ascii=False), file=sys.stderr)
    except (OSError, ValueError, UnicodeError):
        print('{"error":"Could not read the configuration or JSON payload."}', file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
