#!/usr/bin/env python3
"""Versioned, destination-bound synchronization state with atomic writes and CAS."""

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import tempfile
import sys


class StateError(Exception):
    pass


DATA_FIELDS = {"items", "resources", "stories", "identity", "transitions", "verification", "publisher"}
PRIVATE_FIELDS = {"pat", "token", "password", "authorization", "secret", "credentials",
                  "credential", "apikey", "apitoken", "accesstoken", "refreshtoken", "clientsecret"}


def validate_private_content(value, secrets=()):
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if (normalized in PRIVATE_FIELDS
                    or key.lower().endswith(("_pat", "_token", "_secret", "_password", "_api_key"))):
                raise StateError("Credential fields are forbidden in synchronization state.")
            validate_private_content(key, secrets)
            validate_private_content(item, secrets)
    elif isinstance(value, list):
        for item in value:
            validate_private_content(item, secrets)
    elif isinstance(value, str):
        if (any(secret and secret in value for secret in secrets)
                or re.search(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9_+/=.-]{16,}", value)):
            raise StateError("Credential values are forbidden in synchronization state.")


def validate_data(data, secrets=()):
    if not isinstance(data, dict) or set(data) - DATA_FIELDS:
        raise StateError("State data contains unsupported fields.")
    for key, value in data.items():
        expected = list if key == "transitions" else dict
        if not isinstance(value, expected):
            raise StateError("State section has an invalid type.")
    validate_private_content(data, secrets)


def validate_target(target):
    allowed = {"provider", "base_url", "project", "repository"}
    if (not isinstance(target, dict) or set(target) - allowed
            or not all(isinstance(target.get(k), str) and target[k]
                       for k in ("provider", "base_url", "project"))
            or ("repository" in target and not isinstance(target["repository"], str))):
        raise StateError("Target must contain provider, base_url, project, and optional repository only.")
    # No credentials or query parameters belong in the destination binding.
    from tracker_api import validate_base
    validate_base(target["base_url"])


def read_state(path, target, secrets=()):
    validate_target(target)
    validate_private_content(target, secrets)
    if not path.exists():
        return {"schema_version": 1, "revision": 0, "target": target, "data": {}}
    value = json.loads(path.read_text())
    if (not isinstance(value, dict) or set(value) != {"schema_version", "revision", "target", "data"}
            or type(value.get("schema_version")) is not int or value["schema_version"] != 1
            or value.get("target") != target
            or not isinstance(value.get("revision"), int)
            or isinstance(value.get("revision"), bool) or value["revision"] < 1
            or not isinstance(value.get("data"), dict)):
        raise StateError("Unsupported state schema or mismatched destination. Do not overwrite this state.")
    validate_data(value["data"], secrets)
    return value


@contextmanager
def locked(path):
    lock = path.with_name(path.name + ".lock")
    try:
        lock.mkdir()
    except FileExistsError:
        raise StateError("State is locked. Verify the owning session before recovering a stale lock.") from None
    try:
        yield
    finally:
        lock.rmdir()


def write_state(path, target, data, expected_revision, secrets=()):
    validate_data(data, secrets)
    if type(expected_revision) is not int or expected_revision < 0:
        raise StateError("Expected revision must be a nonnegative integer.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked(path):
        previous = read_state(path, target, secrets)
        if previous["revision"] != expected_revision:
            raise StateError("State changed in another session. Read again and reconcile before saving.")
        value = {**previous, "revision": expected_revision + 1, "data": data}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=".scrum-state-", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["read", "write"])
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--target-file", type=Path, required=True)
    parser.add_argument("--data-file", type=Path)
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    try:
        # Never use inherited environment configuration implicitly.
        from tracker_api import load_env
        env_path = args.env_file or (Path(".env") if Path(".env").is_file() else None)
        env = load_env(env_path) if env_path is not None else {}
        secrets = [value for key, value in env.items()
                   if key.endswith(("_PAT", "_TOKEN", "_SECRET", "_PASSWORD")) and value]
        target = json.loads(args.target_file.read_text())
        if args.command == "write":
            if args.data_file is None or args.expected_revision is None or args.expected_revision < 0:
                raise StateError("Write requires --data-file and a nonnegative --expected-revision.")
            result = write_state(args.file, target, json.loads(args.data_file.read_text()),
                                 args.expected_revision, secrets)
            result = {key: result[key] for key in ("schema_version", "revision", "target")}
        else:
            result = read_state(args.file, target, secrets)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception:
        # Do not echo untrusted state or configuration values.
        print('{"error":"State operation failed. Check target, schema, lock, and expected revision."}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
