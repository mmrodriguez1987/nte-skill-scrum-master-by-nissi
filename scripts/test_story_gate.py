import copy
import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from story_gate import evaluate as gate_evaluate
import story_gate


def binding():
    return {"schema_version": 1, "story_id": "APP-42",
            "tracker_target": {"provider": "jira-cloud", "base_url": "https://example.test", "project": "APP"},
            "primary_pr_id": "acme/app#1",
            "required_prs": {"acme/app#1": {"provider": "github", "api_base": "https://api.github.com",
                "repository": "acme/app", "repository_id": 10, "number": 1, "target_branch": "main"}}}


def evaluate(story, expected=None):
    return gate_evaluate(story, binding() if expected is None else expected)


def fixture():
    return {"story_id": "APP-42", "tracker_target": binding()["tracker_target"],
            "acceptance_verified": True, "done_verified": True,
            "primary_pr_id": "acme/app#1", "required_pr_ids": ["acme/app#1"],
            "required_pr_set_verified": True,
            "prs": {"acme/app#1": {
                "provider": "github", "fresh_read_verified": True,
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "pr": {"number": 1, "url": "https://api.github.com/repos/acme/app/pulls/1",
                       "base": {"ref": "main", "repo": {"full_name": "acme/app", "id": 10}},
                       "head": {"sha": "head-1"}, "user": {"id": 1}, "state": "open", "draft": False},
                "reviews": [{"id": 1, "user": {"id": 2}, "state": "APPROVED",
                             "pull_request_url": "https://api.github.com/repos/acme/app/pulls/1",
                             "commit_id": "head-1", "submitted_at": "2026-01-01T00:00:00Z"}],
                "policy": {"verified": True, "head_sha": "head-1", "minimum_approvals": 1,
                           "required_reviewer_ids": [2], "requirements_satisfied": True}}}}


class GateTests(unittest.TestCase):
    def test_one_current_approved_pr_allows_closure(self):
        self.assertTrue(evaluate(fixture())["can_close"])

    def test_missing_or_incomplete_evidence_blocks_closure(self):
        for key in ["acceptance_verified", "done_verified", "required_pr_set_verified"]:
            value = fixture()
            value[key] = False
            self.assertFalse(evaluate(value)["can_close"])
        value = fixture()
        value["prs"] = {}
        self.assertFalse(evaluate(value)["can_close"])

    def test_stale_revoked_draft_author_and_changes_requested_are_blocked(self):
        for mutate in [
            lambda p: p["pr"]["head"].update(sha="new-head"),
            lambda p: p["reviews"][0].update(state="DISMISSED"),
            lambda p: p["reviews"][0].update(state="CHANGES_REQUESTED"),
            lambda p: p["reviews"][0]["user"].update(id=1),
            lambda p: p["pr"].update(draft=True),
            lambda p: p.update(observed_at=(datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat()),
            lambda p: p["policy"].update(required_reviewer_ids=[3]),
            lambda p: p["pr"]["base"]["repo"].update(full_name="other/repo"),
        ]:
            value = fixture()
            mutate(value["prs"]["acme/app#1"])
            self.assertFalse(evaluate(value)["can_close"])

    def test_second_required_pr_must_also_be_approved(self):
        value = fixture()
        value["required_pr_ids"].append("acme/app#2")
        self.assertFalse(evaluate(value)["can_close"])
        second = copy.deepcopy(value["prs"]["acme/app#1"])
        second["pr"]["number"] = 2
        second["pr"]["url"] = "https://api.github.com/repos/acme/app/pulls/2"
        second["reviews"][0]["pull_request_url"] = second["pr"]["url"]
        value["prs"]["acme/app#2"] = second
        expected = binding()
        expected["required_prs"]["acme/app#2"] = {**expected["required_prs"]["acme/app#1"], "number": 2}
        self.assertTrue(evaluate(value, expected)["can_close"])
        self.assertFalse(evaluate(value)["can_close"])

    def test_merge_without_approval_does_not_close_story(self):
        value = fixture()
        item = value["prs"]["acme/app#1"]
        item["pr"].update(state="closed", merged=True)
        item["reviews"] = []
        self.assertFalse(evaluate(value)["can_close"])

    def test_azure_votes_need_current_iteration_coverage(self):
        value = fixture()
        item = value["prs"].pop("acme/app#1")
        value.update(primary_pr_id="repo-id#7", required_pr_ids=["repo-id#7"])
        value["prs"]["repo-id#7"] = item
        item["provider"] = "azure-repos"
        item["pr"] = {"repository": {"id": "repo-id", "project": {"id": "project-id"}}, "pullRequestId": 7,
                      "url": "https://dev.azure.com/org/project-id/_apis/git/repositories/repo-id/pullRequests/7",
                      "targetRefName": "refs/heads/main",
                      "lastMergeSourceCommit": {"commitId": "head-1"}, "createdBy": {"id": "author"},
                      "reviewers": [{"id": "reviewer", "vote": 10}], "isDraft": False, "status": "active"}
        item["policy"]["required_reviewer_ids"] = ["reviewer"]
        item["reviewed_heads"] = {"reviewer": "head-1"}
        expected = binding()
        expected.update(primary_pr_id="repo-id#7", required_prs={"repo-id#7": {
            "provider": "azure-repos", "api_base": "https://dev.azure.com/org", "project_id": "project-id",
            "repository_id": "repo-id", "number": 7, "target_branch": "refs/heads/main"}})
        self.assertTrue(evaluate(value, expected)["can_close"])
        item["reviewed_heads"]["reviewer"] = "old-head"
        self.assertFalse(evaluate(value, expected)["can_close"])
        item["reviewed_heads"]["reviewer"] = "head-1"
        for author in [None, {}, {"id": ""}]:
            item["pr"]["createdBy"] = author
            self.assertFalse(evaluate(value, expected)["can_close"])

    def test_cross_pr_review_and_wrong_destination_are_blocked(self):
        mutations = [
            lambda item: item["reviews"][0].update(pull_request_url="https://api.github.com/repos/other/repo/pulls/9"),
            lambda item: item["pr"].update(url="https://other-host.test/repos/acme/app/pulls/1"),
            lambda item: item["pr"]["base"].update(ref="unrelated-branch"),
            lambda item: item["pr"]["base"]["repo"].update(id=99),
        ]
        for mutate in mutations:
            value = fixture()
            mutate(value["prs"]["acme/app#1"])
            self.assertFalse(evaluate(value)["can_close"])

    def test_author_identity_and_independent_binding_are_mandatory(self):
        for author in [None, {}, {"id": None}, {"id": ""}, {"id": True}]:
            value = fixture()
            value["prs"]["acme/app#1"]["pr"]["user"] = author
            self.assertFalse(evaluate(value)["can_close"])
        value = fixture()
        value["prs"]["acme/app#1"]["pr"].pop("user")
        value["prs"]["acme/app#1"]["reviews"][0]["user"]["id"] = 1
        value["prs"]["acme/app#1"]["policy"]["required_reviewer_ids"] = [1]
        self.assertFalse(evaluate(value)["can_close"])
        self.assertFalse(evaluate(fixture(), {})["can_close"])
        value = fixture()
        value["story_id"] = "APP-OTHER"
        self.assertFalse(evaluate(value)["can_close"])

    def test_malformed_policy_and_missing_review_binding_fail_closed(self):
        for field in ["minimum_approvals", "required_reviewer_ids", "head_sha"]:
            value = fixture()
            value["prs"]["acme/app#1"]["policy"].pop(field)
            self.assertFalse(evaluate(value)["can_close"])
        value = fixture()
        value["prs"]["acme/app#1"]["reviews"][0].pop("pull_request_url")
        self.assertFalse(evaluate(value)["can_close"])

    def test_cli_uses_independent_binding_and_blocks_another_story(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence_file = Path(folder) / "evidence.json"
            binding_file = Path(folder) / "binding.json"
            evidence_file.write_text(json.dumps(fixture()))
            binding_file.write_text(json.dumps(binding()))
            argv = ["story_gate.py", str(evidence_file), "--binding-file", str(binding_file)]
            output = io.StringIO()
            with patch.object(sys, "argv", argv), contextlib.redirect_stdout(output):
                self.assertEqual(story_gate.main(), 0)
            self.assertTrue(json.loads(output.getvalue())["can_close"])
            changed = binding()
            changed["story_id"] = "OTHER-1"
            binding_file.write_text(json.dumps(changed))
            with patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(story_gate.main(), 1)

    def test_cli_rejects_incomplete_and_malformed_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence_file = Path(folder) / "evidence.json"
            binding_file = Path(folder) / "binding.json"
            binding_file.write_text(json.dumps(binding()))
            argv = ["story_gate.py", str(evidence_file), "--binding-file", str(binding_file)]
            for content in ["null", "[]", "{bad-json", json.dumps({"story_id": "APP-42"})]:
                evidence_file.write_text(content)
                with patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(story_gate.main(), 1)


if __name__ == "__main__":
    unittest.main()
