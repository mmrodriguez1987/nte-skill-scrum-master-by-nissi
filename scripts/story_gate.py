#!/usr/bin/env python3
"""Evaluate story closure using freshly collected provider evidence; no writes."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from urllib.parse import quote

from tracker_api import SafeError, validate_base
from scrum_state import StateError


def positive_id(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def github_approval(pr, reviews, policy):
    head = pr.get("head", {}).get("sha")
    author = pr.get("user", {}).get("id")
    if (not positive_id(author) or not nonempty(head) or not isinstance(reviews, list)
            or not isinstance(pr.get("draft"), bool)):
        return False
    latest = {}
    for review in sorted(reviews, key=lambda r: (r.get("submitted_at") or "", r.get("id", 0))):
        if (not isinstance(review, dict) or not positive_id(review.get("user", {}).get("id"))
                or not positive_id(review.get("id"))
                or review.get("pull_request_url") != pr.get("url")
                or not nonempty(review.get("submitted_at"))):
            return False
        if review.get("state") in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            latest[review.get("user", {}).get("id")] = review
    approved = set()
    blocked = False
    for user_id, review in latest.items():
        if user_id is None or user_id == author:
            continue
        if review.get("state") == "CHANGES_REQUESTED":
            blocked = True
        if review.get("state") == "APPROVED" and review.get("commit_id") == head:
            approved.add(str(user_id))
    return approval_result(head, approved, blocked, policy,
                           not pr.get("draft", True)
                           and (pr.get("state") == "open"
                                or (pr.get("state") == "closed" and pr.get("merged") is True)))


def azure_approval(pr, policy, reviewed_heads):
    head = pr.get("lastMergeSourceCommit", {}).get("commitId")
    author = pr.get("createdBy", {}).get("id")
    if (not nonempty(author) or not nonempty(head) or not isinstance(pr.get("reviewers"), list)
            or not isinstance(pr.get("isDraft"), bool) or not isinstance(reviewed_heads, dict)):
        return False
    approved = set()
    blocked = False
    for reviewer in pr.get("reviewers", []):
        user_id = reviewer.get("id")
        if not nonempty(user_id) or type(reviewer.get("vote")) is not int:
            return False
        if user_id == author or reviewer.get("isContainer"):
            continue
        vote = reviewer["vote"]
        if vote in {-10, -5}:
            blocked = True
        # Conservative: approval-with-suggestions is not plain approval.
        if vote == 10 and reviewed_heads.get(user_id) == head:
            approved.add(str(user_id))
    return approval_result(head, approved, blocked, policy,
                           not pr.get("isDraft", True)
                           and pr.get("status") in {"active", "completed"})


def approval_result(head, approved, blocked, policy, usable):
    reviewer_ids = policy.get("required_reviewer_ids")
    if (not isinstance(reviewer_ids, list)
            or not all(positive_id(i) or nonempty(i) for i in reviewer_ids)):
        return False
    required = set(map(str, reviewer_ids))
    minimum = policy.get("minimum_approvals")
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 0:
        return False
    return bool(head and usable and not blocked and policy.get("verified") is True
                and policy.get("head_sha") == head
                and policy.get("requirements_satisfied") is True
                and len(approved) >= max(1, minimum) and required <= approved)


def matches_binding(pr_id, item, expected):
    if item.get("provider") != expected.get("provider"):
        return False
    base = expected["api_base"]
    validate_base(base)
    if base != base.rstrip("/") or not positive_id(expected.get("number")):
        return False
    raw = item["pr"]
    repo_id = expected["repository_id"]
    number = expected["number"]
    branch = expected["target_branch"]
    if not nonempty(branch):
        return False
    if expected["provider"] == "github":
        repo = raw["base"]["repo"]
        name = expected["repository"]
        if not nonempty(name) or len(name.split("/")) != 2 or not positive_id(repo_id):
            return False
        url = f"{base}/repos/{name}/pulls/{number}"
        return (pr_id == f"{name}#{number}" and raw.get("url") == url
                and raw.get("number") == number and positive_id(raw.get("number"))
                and repo.get("full_name") == name and repo.get("id") == repo_id
                and positive_id(repo.get("id")) and raw["base"].get("ref") == branch)
    if expected["provider"] == "azure-repos":
        project = expected["project_id"]
        if not nonempty(repo_id) or not nonempty(project):
            return False
        url = (f"{base}/{quote(project, safe='')}/_apis/git/repositories/"
               f"{quote(repo_id, safe='')}/pullRequests/{number}")
        return (pr_id == f"{repo_id}#{number}" and raw.get("url") == url
                and raw.get("pullRequestId") == number and positive_id(raw.get("pullRequestId"))
                and raw["repository"].get("id") == repo_id
                and raw["repository"]["project"].get("id") == project
                and raw.get("targetRefName") == branch)
    return False


def evaluate(story, binding):
    try:
        return _evaluate(story, binding)
    except (KeyError, TypeError, ValueError, AttributeError, SafeError, StateError):
        return {"can_close": False, "reasons": ["Invalid or incomplete evidence/binding."]}


def _evaluate(story, binding):
    reasons = []
    if (type(binding.get("schema_version")) is not int or binding["schema_version"] != 1
            or not nonempty(binding.get("story_id"))
            or not isinstance(binding.get("tracker_target"), dict)
            or not isinstance(binding.get("required_prs"), dict) or not binding["required_prs"]
            or story.get("story_id") != binding["story_id"]
            or story.get("tracker_target") != binding["tracker_target"]):
        return {"can_close": False, "reasons": ["Missing or mismatched independent story binding."]}
    from scrum_state import validate_target
    validate_target(binding["tracker_target"])
    if story.get("acceptance_verified") is not True:
        reasons.append("Acceptance criteria are not verified.")
    if story.get("done_verified") is not True:
        reasons.append("Definition of Done is not verified.")
    ids = story.get("required_pr_ids", [])
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i for i in ids):
        reasons.append("A nonempty required PR set must be established.")
        ids = []
    if (story.get("primary_pr_id") not in ids
            or story.get("primary_pr_id") != binding.get("primary_pr_id")
            or set(ids) != set(binding["required_prs"]) or len(ids) != len(set(ids))):
        reasons.append("The primary and complete required PR set must match independent state.")
    if story.get("required_pr_set_verified") is not True:
        reasons.append("The complete required PR set has not been verified.")
    evidence = story.get("prs", {})
    for pr_id in dict.fromkeys(ids):
        item = evidence.get(pr_id, {})
        if not item or item.get("fresh_read_verified") is not True:
            reasons.append(f"{pr_id}: fresh provider evidence is missing.")
            continue
        raw = item.get("pr", {})
        policy = item.get("policy", {})
        try:
            observed = datetime.fromisoformat(item["observed_at"].replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - observed).total_seconds()
            fresh = 0 <= age <= 300
        except (KeyError, TypeError, ValueError):
            fresh = False
        if not fresh:
            reasons.append(f"{pr_id}: evidence is missing a recent UTC observation time.")
            continue
        expected = binding["required_prs"].get(pr_id, {})
        if not matches_binding(pr_id, item, expected):
            reasons.append(f"{pr_id}: provider, host, repository, PR, project, or target branch mismatch.")
            continue
        if item["provider"] == "github":
            ok = github_approval(raw, item.get("reviews", []), policy)
        elif item["provider"] == "azure-repos":
            ok = azure_approval(raw, policy, item.get("reviewed_heads", {}))
        else:
            ok = False
        if not ok:
            reasons.append(f"{pr_id}: current approval or required review policy is not satisfied.")
    return {"can_close": not reasons, "reasons": reasons}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_file", type=Path)
    parser.add_argument("--binding-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = evaluate(json.loads(args.evidence_file.read_text()),
                          json.loads(args.binding_file.read_text()))
    except (OSError, ValueError, TypeError, AttributeError):
        result = {"can_close": False, "reasons": ["Invalid or unreadable evidence."]}
    print(json.dumps(result))
    return 0 if result["can_close"] else 1


if __name__ == "__main__":
    sys.exit(main())
