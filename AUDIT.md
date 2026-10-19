# SCRUM MASTER audit

Date: 2026-10-19
Scope: skill instructions, linked references, examples, configuration, REST helper, and local tests.

## Remediation follow-up

The findings below describe the audited baseline. A subsequent remediation added strict file-based configuration, explicit environment-only mode, decoded credential checks, preserved pagination metadata, sanitized diagnostics, separate Git PAT routing, Azure PAT/access-token modes, a tested provider-evidence closure checker, and atomic versioned state writes. Instructions now define primary versus additional required PRs, neutral Conventional Commits, completion-automation protection, and single-writer publication. Draft examples require removing instructional notes before publication.

F1–F4 have local regression coverage. F5 is addressed through operational instructions and a local approval gate; enforcement against external automation still requires provider-side configuration. F6 now has GitHub/Azure Repos evidence evaluation and tests, but real-instance API/policy discovery remains unvalidated. State writes are protected locally; remote operations are single-writer and require reconciliation after uncertain outcomes. The original observations are retained below as history, not a claim that every baseline issue remains unfixed.

## Baseline assessment (before remediation)

The intended workflow is coherent, but the current implementation is not yet validated end to end against Jira or Azure DevOps. The existing ten unit tests pass. Additional offline probes reproduced pagination and credential-validation failures that those tests do not cover. No real credentials, external writes, or runtime changes were used during this audit.

P1 means a high-priority correctness or credential-protection issue. P2 means a material reliability or integration gap. The recommendations below describe the original baseline; see the remediation follow-up above for their current status.

## Confirmed findings

### F1 — P1: redaction destroys Jira pagination cursors

Location: `scripts/tracker_api.py:97-108`.

`scrub()` replaces every value whose key contains `token`. A normal enhanced JQL response containing `nextPageToken` therefore returns `[REDACTED]` instead of the cursor needed for the next page. This was reproduced using an entirely fictitious response.

Impact: the agent cannot complete modern Jira searches through the helper. It may miss existing work or be forced to stop before completing duplicate detection.

Recommendation: distinguish authentication secrets from operational pagination cursors. Redact known credential values and narrowly identified authentication fields, while retaining supported pagination metadata. Add a regression test that traverses two mocked JQL pages.

Official reference: https://confluence.atlassian.com/jirakb/run-jql-search-query-using-jira-cloud-rest-api-1289424308.html

### F2 — P1: JSON-escaped credentials bypass the outgoing body check

Location: `scripts/tracker_api.py:167-175`.

The helper parses the payload with `json.loads()` but discards the decoded value, then checks raw bytes for the PAT/header. A fake credential encoded with a JSON Unicode escape passes the check and is sent as a body value. The remote JSON parser reconstructs the original credential. This was reproduced through the actual CLI entry point using a mocked HTTP transport.

Impact: a secret accidentally inserted in a description may be persisted remotely despite the helper's stated credential protection. This does not imply that current instructions intentionally generate such payloads.

Recommendation: validate decoded JSON recursively, including keys, against credential values and authentication representations; check the decoded URL as well. Keep prevention distinct from response redaction. Add encoded-body regression cases.

### F3 — P2: required response-header metadata is discarded

Location: `scripts/tracker_api.py:124-132`; `references/platforms.md` REST transport section.

The helper returns only status and body. Some Azure APIs, including Graph user listing, expose their pagination cursor in `X-MS-ContinuationToken`. The caller cannot retrieve it through this interface. Retry guidance from response headers is also unavailable. An offline probe confirmed that a supplied continuation header is absent from the helper result.

Impact: identity discovery that uses these APIs cannot enumerate all pages; rate-limit handling lacks provider-supplied timing information. This is separate from F1, which concerns body metadata.

Recommendation: expose a small, sanitized allowlist of operational headers such as continuation and retry metadata rather than all headers. Cover header pagination and 429 behavior in tests. Calls to another API host also require explicitly configured authentication routing; do not forward credentials by following arbitrary links.

Official reference: https://learn.microsoft.com/en-us/rest/api/azure/devops/graph/users/list?view=azure-devops-rest-7.1

### F4 — P2: a missing explicit .env silently falls back to inherited configuration

Location: `scripts/tracker_api.py:25-41`, `139-153`.

`load_env()` does not fail when its file does not exist, and process variables override the file when it does. Environment-only configuration is documented, but the CLI does not distinguish that intentional mode from a typo in an explicitly selected project file. A probe with a missing explicit path and inherited fake credentials completed a mocked write.

Impact: a caller expecting the selected project's credentials can unintentionally use another inherited destination/account. The current tests explicitly validate environment precedence but not explicit-file failure or destination mismatch.

Recommendation: fail for a missing explicitly selected file; make environment-only operation deliberate. Resolve provider, destination, project, and authenticated identity before publication and bind the manifest to that resolved target. Stop if the target changes on resumption.

## Instruction and integration findings

### F5 — P1: the closure rule does not address automatic work-item completion

Location: `references/execution.md:59-70` and the PR writing example.

The manual transition gate checks every required PR, acceptance criteria, and Done. The instructions do not address platform features that transition linked work items outside that gate. Azure supports automatic completion of associated work items during PR completion and resolution mentions in commits.

Failure scenario: a story needs two PRs; one is approved and merged with linked-item completion enabled while the other remains unapproved. The platform can close the story before the skill reaches its final transition check. This scenario follows the documented provider behavior; it was not exercised against a live project.

Recommendation: discover existing completion automation, avoid introducing completion keywords/options that bypass the story gate, and reconcile premature closure when observed. Do not silently change repository-wide policies or existing automation. For an invariant that must hold even outside Claude sessions, use a provider-side validation/automation rule as separately authorized configuration.

Official references:
- https://learn.microsoft.com/en-us/azure/devops/repos/git/complete-pull-requests?view=azure-devops
- https://learn.microsoft.com/en-us/azure/devops/repos/git/resolution-mentions?view=azure-devops

### F6 — P2: PR approval checks lack provider-specific executable coverage

Location: `references/execution.md:61-70`; `scripts/test_tracker_api.py`.

The skill correctly requires valid current approval, but the executable helper only offers generic Jira/Azure REST transport. It does not normalize review states, required reviewers, review coverage after new commits, or missing Git access. Current tests do not exercise these decisions. For Jira paired with GitHub/Bitbucket, the documentation permits an authorized connector but provides no configured credential/adapter path when none is available.

Impact: the most important business rule depends on the agent interpreting provider-specific review data correctly during every run. Unsupported access should keep the story open, as currently instructed, but can prevent the requested workflow from completing.

Recommendation: define an explicit Git-provider configuration and approval contract, with evidence fields for repository, PR, current head/iteration, reviewer decisions, required-reviewer status, and verification time. Add behavioral cases for approval, changes requested, stale approval, two required PRs, and unavailable review access. Preserve the user's rule: approval remains mandatory; merge is additionally required only when Done requires it.

## Further improvements

### I1 — Define a versioned synchronization schema and crash-safe persistence

`reference.md` describes manifest/state fields in prose but provides no schema, writer, atomic-save behavior, or concurrency contract. A partial write or simultaneous sessions could lose mappings. Add schema versioning, destination binding, atomic replacement, and a project-local lock or explicit single-writer rule before relying on unattended resumption. Treat this as a reliability improvement, not a reproduced corruption incident.

### I2 — Preserve useful validation errors without exposing credentials

All HTTP error bodies are omitted. A 400 caused by a missing required field, an invalid transition, or an unassignable user becomes the same generic message. Return bounded, sanitized provider error codes and field validation messages, plus correlation/retry metadata where appropriate, without dumping raw bodies or headers.

### I3 — Split complete writing examples from draft scaffolding

The PR example contains drafting instructions and pending validation; the Bug example describes a reproduced defect while its evidence is still pending. Both are labeled as examples and the shared guidance prohibits invented facts, so this is not a direct contradiction. However, pairing a completed illustrative example with a separate reusable template would make accidental publication of instructional text less likely. Add a publication check for unresolved drafting notes, without banning legitimate pending questions in backlog items.

## Validation performed

- Read all skill instructions, references, examples, configuration, and helper code.
- Ran the existing ten unit tests: all passed.
- Reproduced F1–F4 using synthetic data, temporary files, inherited fake configuration, and mocked HTTP responses.
- Checked relevant provider documentation for Jira pagination, Azure pagination, and automatic work-item completion.
- Did not create boards, work items, PRs, or remote automations.

Recommended order: F1/F2, then F3/F4, then F5/F6 and behavioral integration validation in a disposable project. Address persistence and diagnostics before unattended operation.
