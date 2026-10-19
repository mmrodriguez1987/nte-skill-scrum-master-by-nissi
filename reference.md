# From technical analysis to backlog

## Choose the item type

| Conceptual type | When to use it | Useful content |
|---|---|---|
| Epic | Broad goal spanning several outcomes | Outcome, scope, exclusions, success signal |
| Feature | Capability grouping stories when useful | Users, behavior, and boundaries |
| Story / PBI | Verifiable increment that fits within a sprint | Need, value, acceptance criteria, dependencies |
| Task / Sub-task | Concrete work needed to complete a story | Parent, expected change, verification |
| Bug | Deviation from expected existing behavior | Expected/actual behavior, reproduction, environment, impact, regression coverage |
| Spike | Uncertainty preventing a decision or estimate | Question, effort limit, decision evidence |

A risk is not a confirmed bug. Missing functionality is not necessarily a bug: check expected behavior and scope. Use an available remote type for spikes; do not invent types.

## Executable stories and tasks

Split stories by scenarios, rules, or journeys delivering value. UI, API, and database changes are often tasks within a vertical story; avoid presenting isolated layers as complete increments. Technical enabling work may be a separate item with an explicit outcome and rationale.

Each story includes a stable local ID, requirement source, parent and title, purpose/value, observable acceptance criteria, dependency IDs, open questions, and a provisional size when useful for planning. Use Given/When/Then when it clarifies scenarios. Consider relevant errors, permissions, and edge cases without silently expanding scope.

Each task describes its outcome and verification; add likely components when known. Include tests, migrations, and documentation when needed without repeating an identical checklist for every story.

Example: “The customer can recover account access” may include link generation, expiration/single-use validation, a form, and tests for agreed scenarios. “Create a token table” describes a task rather than the complete value.

## Sprint planning

- Define a verifiable goal related to the product goal.
- Check availability, duration/dates, support work, and comparable past performance. Do not impose two weeks or a reserve percentage without labeling it as a proposal.
- Select stories that jointly meet the goal and their dependencies. Explain what remains out of scope. Do not combine task hours and story points into a single capacity measure.
- Identify decisions needed to unblock work; use spikes when uncertainty prevents planning.
- For Claude or other agents, use execution blocks with dependencies and verification. Do not infer velocity from tokens or response time; forecasts need comparable evidence and explicit limitations.
- Separate story acceptance criteria from the shared Definition of Done. If Done is missing, propose one pending agreement. Do not declare a story complete just because its subtasks are closed: all required PRs must have valid approval, and acceptance criteria and Done must also be met. See [references/execution.md](references/execution.md).

## Persistence and resumption

Use `.scrum/backlog.md`, `.scrum/sprint-plan.md`, `.scrum/sync-manifest.json`, and `.scrum/sync-state.json` in the target project as actually needed. Avoid redundant files for small tasks.

The manifest records the provider/destination without secrets and operations containing `local_id`, `action`, `remote_id` when available, `type`, `parent_local_id`, `fields`, `depends_on`, and iteration. Preserve local IDs when refining titles. Dependencies and parenthood are separate relationships.

State records the destination, local/remote IDs, links, action, timestamp, remote revision when available, and pending/complete verification. Include board/filter/team/area IDs, the authenticated identity, verified assignees, transitions, and PRs with their head/iteration and approval evidence. Check existing items through mappings and persistent markers; titles alone are insufficient. Store markers in a permitted field, label, or body according to the configuration.

To resume, read state, query existing items, and continue pending operations. If a POST timed out before its ID was saved, search for its marker before retrying; if uncertainty cannot be resolved, request a decision for that item. On concurrent changes, read again and recalculate the diff. Preserve unrelated content contributed by others.

### Versioned, destination-bound state

Use `scripts/scrum_state.py` for synchronization state instead of overwriting JSON directly. Its envelope contains `schema_version: 1`, monotonic `revision`, a fixed `target`, and a `data` object. The target contains `provider`, `base_url`, `project`, and optional `repository`, using resolved IDs/canonical base URLs without secrets. Keep the target in `.scrum/target.json` and compare it with newly resolved configuration before remote writes. A changed account/identity also requires revalidating assignment and access; it is not permission to reassign existing work.

```bash
python3 <skill>/scripts/scrum_state.py read --file .scrum/sync-state.json --target-file .scrum/target.json
python3 <skill>/scripts/scrum_state.py write --file .scrum/sync-state.json --target-file .scrum/target.json --data-file .scrum/state-data.json --expected-revision 0
```

For an absent state file, read returns revision 0. Use the revision actually read on each write; never guess or blindly retry a revision conflict. Writes lock the state file, flush a temporary file, and replace atomically; a revision mismatch or different target blocks the write. Do not remove a stale lock without checking its owning session. Avoid using these files on storage without the required local filesystem atomicity guarantees.

Only one publishing session may perform remote operations for a project/target at a time. The helper's short state-write lock does not cover the entire remote create sequence. Check for other active publishers before publication; if exclusivity cannot be established, keep the run read-only. Use an explicit workflow-level lease before introducing parallel/unattended publishers. Local state does not provide a transaction across a remote API and the filesystem; retain markers and reconciliation for interrupted remote writes.

Store item/resource mappings, authenticated identity IDs, required PR sets, transition evidence, and verification results under `data`. Never store PATs, access tokens, authentication headers, or raw private `.env` contents. Version manifests with `schema_version: 1` as well, and validate parent/dependency references and local ID uniqueness before publication.

The state-data sections are allowlisted: `items`, `resources`, `stories`, `identity`, `verification`, and `publisher` must be objects; `transitions` must be an array. Put each story's independent PR binding and approval evidence under its `stories` entry. Other top-level sections and credential-named fields at any depth are rejected. Legacy state is validated before being returned; do not bypass validation to resume a contaminated file.

Both reads and writes can receive `--env-file <project>/.env` to check known credential values without putting them in arguments. If omitted, a local `.env` is used when present; without one, the structural/credential-field checks still apply but cannot identify an arbitrary unrecognized secret value. Process variables are not implicitly loaded by this helper. Never treat these checks as permission to copy configuration or raw unfiltered responses into state.

Successful writes return only schema version, revision, and target, not the complete saved payload. The `read` command returns validated state for the agent to resume work. Credential detection errors do not echo the forbidden content. If a legacy file is rejected, keep it out of commits and resolve its contamination without displaying its contents; do not automatically delete mappings or reset revision history.
