# SCRUM MASTER — second audit

Date: 2026-10-19
Scope: current skill instructions, examples, credential configuration, REST transport, story closure gate, synchronization state, and existing tests.

## Remediation follow-up

R1: the closure checker now requires an independent story/target binding, compares API host, stable repository identity, PR number, target branch and Azure project, and checks each GitHub review's PR URL. R2: author identities and mandatory provider/policy fields are validated; incomplete evidence fails closed. R3: state sections are allowlisted, credential fields are rejected recursively, known values can be checked through a local environment file, reads validate legacy content, and writes print a summary. R4: HTTP protocol/truncation errors are handled with a structured uncertain-write outcome and no automatic retry. Regression tests cover these corrections. The observations below describe the pre-remediation baseline; real-instance validation and external enforcement limitations still apply.

## Result

The original pagination and environment-selection defects remain corrected in the exercised regression cases. All 27 existing tests pass, and skill structural validation passes. Four additional findings were reproduced offline; the present suite does not cover them. Two are high-priority closure-gate correctness issues, and two concern reliability or defense in depth.

No live accounts, real credentials, remote writes, or runtime implementation changes were used in this audit. This report does not claim that incomplete or mismatched evidence has occurred in production; it demonstrates that the checker accepts such evidence when supplied.

## Findings

### R1 — P1: review evidence is not bound to its PR or expected destination

Locations:
- `scripts/story_gate.py:15-26`: GitHub reviews are grouped by reviewer and checked by commit only.
- `scripts/story_gate.py:94-103`: identity matching uses repository name/ID and PR number but no expected API host or target branch.
- `references/git-workflow.md:85-99`: the evidence contract does not provide a mandatory expected destination/story binding to the executable gate.

Reproduction:
1. Start with `fixture()` from `scripts/test_story_gate.py`.
2. Set its review's `pull_request_url` to a different repository/PR while retaining the same source commit.
3. `evaluate()` still returns `can_close: true`.
4. Changing the raw PR's target branch and repository host also leaves the result true; the checker has no expected host/branch to compare against.

Why it matters: different PRs can share a source commit, and identical owner/repository names can exist on different GitHub Enterprise hosts. An accidentally collected review from another endpoint can therefore count toward the wrong PR. The current `fresh_read_verified` flag does not resolve the explicit mismatch already present in the data.

Recommendation: bind evidence to the story ID, configured API host, repository ID, PR ID, and intended target branch. Compare each GitHub review's `pull_request_url` with the canonical URL of the evaluated PR. Validate Azure evidence against its PR artifact and iteration as applicable. Pass expected bindings independently from the manifest/state instead of deriving both sides from the evidence itself. Reject missing or mismatched bindings.

Regression cases: same commit across two PRs; different Enterprise host with the same owner/repo name; incorrect target branch; correct PR with matching expected bindings.

### R2 — P1: missing author metadata permits author-only approval

Locations:
- `scripts/story_gate.py:12-26`: absent GitHub `user.id` becomes `None`.
- `scripts/story_gate.py:33-46`: absent Azure `createdBy.id` becomes `None`.

Reproduction:
1. Start with the valid GitHub fixture.
2. Set the approving reviewer and required reviewer to the actual PR author.
3. Omit the raw PR's `user` object.
4. `evaluate()` returns `can_close: true`.
5. The equivalent Azure Repos case passes when `createdBy` is omitted.

Why it matters: the gate claims to reject malformed/unknown evidence and author-only approvals. Without a known author, it cannot establish that approval came from someone else, yet it counts the vote. This is a fail-open path for incomplete evidence, not a claim that a normal complete provider response lacks author information.

Recommendation: validate mandatory provider fields and their types before evaluating approval. A missing, empty, or invalid author ID must yield an unknown/blocked result. Require stable reviewer identities, correctly typed PR/head/state fields, and complete policy fields. Do not infer validity from truthiness or default missing identity fields to an approvable state.

Regression cases: missing/null/empty author for both providers; actual author-only approval; missing reviewer ID; complete independent approval.

### R3 — P2: synchronization state accepts and echoes credential fields

Locations:
- `scripts/scrum_state.py:54-68`: only checks whether `data` is an object.
- `scripts/scrum_state.py:95`: prints the complete stored data on both read and write.

Reproduction: write `data={"GIT_PAT": "FAKE-NOT-A-REAL-CREDENTIAL"}` using `write_state()`. The helper persists the field and returns it unchanged through `read_state()`; the CLI prints the complete record. No real secret was used.

Why it matters: instructions already prohibit secrets in state, but the new persistence helper does not enforce the “without credentials” condition expressed in its error message. Accidentally saving a configuration dictionary or an unfiltered provider response can persist secrets and expose them in tool output. This is a missing defense, not evidence of an existing credential disclosure.

Recommendation: define and validate an allowlisted state-data schema, reject credential-named fields recursively, and check configured credential values when available without exposing them as arguments. Default successful writes to a revision/target summary rather than echoing the entire payload. Apply the same validation to reads of existing files. Preserve explicit diagnostic access to non-sensitive mappings when needed.

Regression cases: direct and nested credential fields; configuration dictionaries accidentally supplied as state; safe work-item mappings; legacy state containing forbidden fields.

### R4 — P2: truncated HTTP responses bypass safe error handling

Locations:
- `scripts/tracker_api.py:195-213`: `response.read()` can raise exceptions outside the handled sets.
- `scripts/tracker_api.py:261-264`: CLI fallback also omits those exceptions.

Reproduction: mock a response to an authorized POST with status 201 whose `read()` raises `http.client.IncompleteRead`. The exception escapes as `IncompleteRead` instead of producing the expected sanitized structured error. The response may already represent a completed remote creation.

Why it matters: a connection can break after the server creates an item but before the response body is read completely. This path loses the normal uncertainty/reconciliation diagnostic and can produce a traceback. Current network tests simulate `URLError`, not a truncated successful response. The skill's general reconciliation instruction still applies, but the transport should consistently identify this outcome.

Recommendation: handle appropriate `http.client.HTTPException` subclasses, preserve an explicit unknown-write-outcome classification, close resources, and instruct reconciliation rather than retrying. Do not include partial response bytes in output. Add the same protection when reading HTTP error bodies.

Regression cases: truncated GET; truncated 201 after POST; failure reading an error body; no automatic write retry.

## Previous findings: current status

| Previous issue | Current assessment |
|---|---|
| Jira body cursor redacted | Corrected in current regression test |
| Azure operational headers discarded | Corrected for the allowlisted headers exercised |
| JSON-escaped active credentials accepted in request bodies | Corrected in exercised cases |
| Missing selected .env falls back to inherited account | Corrected; explicit environment-only mode is separate |
| External automation bypasses local closure checks | Documented limitation; still requires provider-side enforcement for a cross-session guarantee |
| No executable approval evaluation | Improved with GitHub/Azure Repos evaluation, but R1/R2 must be addressed |
| State writes lack atomicity/revision binding | Improved locally; remote publication remains single-writer and nontransactional |
| Opaque HTTP validation errors | Improved with bounded sanitized details; R4 remains |

## Remaining operational limitations

- End-to-end provisioning, field mapping, identity assignment, PR policy discovery, and transitions have not been validated against real Jira/Azure projects.
- A local gate evaluates evidence supplied by the agent. It does not authenticate that evidence itself or enforce a remote workflow against other users/automation.
- The short state-write lock does not serialize the entire remote publication sequence. The current instructions correctly require one publisher per target; unattended concurrency would need a real workflow lease.
- The evidence collector and policy normalization are still performed by the agent. Future work should make provider collection reproducible rather than adding more trusted booleans.

## Validation performed

- Existing unit tests: 27 passed.
- Skill structural validation: passed.
- Offline probes: R1–R4 reproduced with synthetic fixtures, temporary files, and mocked responses.
- Runtime source modifications during audit: none.

Recommended next step: address R1/R2 first, then R3/R4, with regression cases before real-project integration validation.

## Official references consulted

- GitHub review fields, including `pull_request_url`, reviewer identity, and `commit_id`: https://docs.github.com/en/rest/pulls/reviews
- Azure PR response fields: https://learn.microsoft.com/en-us/rest/api/azure/devops/git/pull-requests/get-pull-request?view=azure-devops-rest-7.1
- Python HTTP exceptions, including `IncompleteRead`: https://docs.python.org/3/library/http.client.html
