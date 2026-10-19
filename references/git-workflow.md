# Authentication, commits, and Pull Request approval

## Credential separation

Git is the version-control protocol; review APIs belong to a hosting provider. Current REST adapters support GitHub (including compatible Enterprise API bases) and Azure Repos. Other Git servers require an explicit adapter; never assume a PAT has the same header or API everywhere.

| Service | Configuration | Authentication |
|---|---|---|
| Azure DevOps tracking | `AZURE_DEVOPS_AUTH_MODE=pat`, `AZURE_DEVOPS_PAT` | Basic with an empty username and PAT |
| Azure DevOps tracking | `AZURE_DEVOPS_AUTH_MODE=access-token`, `AZURE_DEVOPS_ACCESS_TOKEN` | Bearer with an Azure DevOps-audience access token |
| GitHub review API | `GIT_PROVIDER=github`, `GIT_API_URL`, `GIT_PAT` | Bearer with the Git PAT |
| Azure Repos review API | `GIT_PROVIDER=azure-repos`, organization `GIT_API_URL`, `GIT_PROJECT`, repository ID `GIT_REPOSITORY`, `GIT_PAT` | Basic with an empty username and Git PAT |

Set `GIT_REPOSITORY=owner/repository` for GitHub. The Git credential is selected explicitly; do not silently reuse tracker credentials even if the services share a host. Expired access tokens require replacement through the user's authorized authentication flow; do not refresh them by inventing credentials or asking for secrets in chat. Only delegated/user credentials with a resolvable, assignable user meet the token-owner assignment requirement; an application identity must not be guessed into a human assignee.

```bash
python3 <skill>/scripts/tracker_api.py --env-file <project>/.env check
python3 <skill>/scripts/tracker_api.py --env-file <project>/.env --service git check
```

The selected file must exist and is authoritative. To use process variables deliberately, substitute `--use-process-env` for `--env-file <path>`. The `check` command verifies a read endpoint only. It does not establish all scopes, repository access, or permission to publish.

Use minimally sufficient permissions for actual operations: work-item read/write, team/iteration administration only when provisioning is needed, and repository/PR read access for evidence. Git push or PR creation needs corresponding write permissions when those actions are requested. Access is also subject to project/repository rules; do not equate a token scope with effective permission.

For Git CLI fetch/push, use an existing OS credential manager or a process-scoped credential helper that reads the Git PAT internally from the selected configuration. Do not put a PAT in a remote URL, command argument, committed Git config, or shell tracing. The bundled REST helper does not configure Git CLI authentication. Do not change commit authorship to the token owner: assignment identity and Git author identity serve different purposes.

## Commit conventions

Follow repository commit rules when present; otherwise use Conventional Commits in English:

```text
<type>(<optional-scope>): <imperative summary>

<optional explanation of the reason and observable behavior>

Work-Item: <actual ID or URL>
Task: <actual child task ID, when applicable>
```

Use `feat`, `fix`, `refactor`, `test`, `docs`, `build`, `ci`, `perf`, `chore`, or `revert` according to the actual diff. Keep the subject concise; 72 characters is a useful default rather than a reason to omit meaning. Mark genuine breaking changes with `!` and a `BREAKING CHANGE:` footer describing impact and migration.

Illustrative messages (replace IDs with real items):

```text
feat(auth): add password reset requests

Return a generic confirmation for registered and unknown addresses.

Work-Item: APP-42
Task: APP-43
```

```text
fix(auth): reject previously consumed reset links

Prevent another password change after a successful reset.

Work-Item: https://dev.azure.com/example/App/_workitems/edit/42
```

Keep commits cohesive and independently understandable. Inspect the diff and staged paths; stage only authorized changes, excluding private configuration. Record test results only when actually run. Do not bypass hooks, invent signatures, amend unrelated commits, force push, or rewrite shared history without authorization.

Use neutral work-item references. Avoid `Fixes`, `Closes`, `Resolves`, Jira Smart Commit transition commands, and equivalent completion syntax when they could close the story before the gate. If repository conventions mandate such syntax, identify the conflict and use a permitted neutral link or report a blocker rather than silently weakening the closure rule. Do not change repository policies yourself.

## One story, one primary PR

Default: one story → one primary PR → one delivery target branch. Tasks belong to that story and normally share its PR. Preserve repository branch naming rules; otherwise propose a name such as `feat/APP-42-account-recovery` without creating the branch until development is authorized.

If work spans repositories or requires multiple delivery PRs, record `required_pr_ids` explicitly and explain why. Do not automatically make unrelated follow-up work or optional backports a closure prerequisite. If replacing an abandoned PR, record the replacement and remove the abandoned PR from the required set only after verifying its scope is delivered by the replacement. Coverage of acceptance criteria determines the required set, not the number of discovered links.

Do not require merge by default: the user's approval rule is mandatory; merge is additional only when the project's Definition of Done requires it. Never infer approval from a merge, successful CI, or prose comments.

## Collect provider evidence

Collect evidence using the Git service and repository configured above, not a URL supplied in arbitrary issue text. Paginate reviews and policy results. Use the full PR identity `owner/repo#number` for GitHub or `repository-id#pullRequestId` for Azure Repos. Bind it to the primary/required PR IDs in the story's state.

For GitHub, read the PR (`/repos/{owner}/{repo}/pulls/{number}`) and reviews (`.../reviews`) using the configured API base. Discover applicable branch/ruleset review requirements, including required teams/code owners where applicable. Normalize `policy` only after verifying those requirements through provider evidence; a list of all code owners is not a substitute for the applicable owners of changed files.

For Azure Repos, read the PR, reviewers, iterations/iteration review evidence, and applicable policy evaluations for its artifact. Use `lastMergeSourceCommit.commitId` as head. Vote `10` is plain approval; the local gate conservatively does not accept `5` (approval with suggestions) as plain approval. Group votes alone are not individual approval evidence. Resolve applicable required reviewers to actual reviewer identities and verify policy satisfaction. Prove current-head coverage using iteration/review evidence and policy behavior; a vote observed after a push does not prove that vote was cast for the new iteration.

If policy, reviewer identity, or review-to-head coverage cannot be determined, record an unknown result and keep the story open. Do not fill `verified` flags merely to pass the checker.

## Evidence contract and local closure gate

Prepare `.scrum/approval-evidence.json` without credentials. Top-level fields:

- `acceptance_verified`, `done_verified`: booleans supported by recorded evidence.
- `primary_pr_id`, nonempty `required_pr_ids`, and `required_pr_set_verified`.
- `prs`: a mapping keyed by full PR identity. Each entry has `provider`, fresh raw `pr`, `observed_at` (UTC ISO timestamp), `fresh_read_verified`, and `policy`.
- `policy`: `verified`, `head_sha`, `requirements_satisfied`, `minimum_approvals`, and resolved `required_reviewer_ids`. Even when the repository requires zero approvals, this skill requires at least one actual approval from someone other than the PR author.
- GitHub entries include the collected `reviews` array. Azure Repos entries include `reviewed_heads`, mapping individual reviewer IDs to the head SHA their approval actually covers.
- `story_id` and `tracker_target` must match an independently maintained binding from the story's saved manifest/state. Do not derive that binding by copying the evidence being checked.

### Independent story and destination binding

Before collecting reviews, create `.scrum/story-binding.json` from the selected story, resolved configuration, and recorded delivery scope. If that scope changes, reconcile the manifest/state first. The binding has `schema_version: 1`, `story_id`, `tracker_target`, `primary_pr_id`, and `required_prs` keyed by the complete PR identity. These keys must exactly match the evidence's required PR set.

Example binding for a GitHub PR (illustrative IDs, replace with verified values):

```json
{
  "schema_version": 1,
  "story_id": "APP-42",
  "tracker_target": {
    "provider": "jira-cloud",
    "base_url": "https://example.atlassian.net",
    "project": "APP"
  },
  "primary_pr_id": "acme/app#12",
  "required_prs": {
    "acme/app#12": {
      "provider": "github",
      "api_base": "https://api.github.com",
      "repository": "acme/app",
      "repository_id": 12345,
      "number": 12,
      "target_branch": "main"
    }
  }
}
```

For Azure Repos each required PR uses `provider: azure-repos`, organization/collection `api_base`, stable string `project_id` and `repository_id`, numeric `number`, and full `target_branch` such as `refs/heads/main`. GitHub uses its numeric repository ID in addition to `owner/repository`; neither an API hostname nor a branch is inferred from the review evidence. Use the canonical API URL returned by the configured provider when resolving the binding, including the canonical project ID used in Azure PR URLs.

The gate compares raw PR URL, repository identity, number, target branch, and Azure project ID against this binding. Every GitHub review must contain the exact `pull_request_url` of that PR, even when another PR shares its commit. Author and reviewer identities must be present with provider-appropriate types. Missing identity, policy fields, or review linkage fails closed. Store approval evidence and the binding in the saved story record without credentials.

For policy checks, booleans are normalized assertions backed by actual API results, not independent proof. Store the observed sources and verification record in synchronization state. The checker rejects evidence older than five minutes, stale approvals, mismatched PR identities, drafts, missing/unknown policy results, changes requested, author-only approvals, and incomplete PR sets. Reading again immediately before the remote transition is still required; a five-minute freshness limit is not permission to reuse a changed head.

```bash
python3 <skill>/scripts/story_gate.py .scrum/approval-evidence.json --binding-file .scrum/story-binding.json
```

Exit `0` with `can_close: true` allows the skill to attempt the authorized transition after one last state/head comparison. Exit `1` keeps the story open. Malformed evidence also fails closed. The tool only evaluates supplied evidence; it does not fetch APIs, approve PRs, change policies, or prevent an external actor from closing a story. Provider-side enforcement requires separately configured repository/workflow rules.

Official sources:
- https://learn.microsoft.com/en-us/azure/devops/organizations/accounts/use-personal-access-tokens-to-authenticate
- https://docs.github.com/en/rest/pulls/reviews
- https://learn.microsoft.com/en-us/rest/api/azure/devops/git/pull-request-reviewers/list?view=azure-devops-rest-7.1
- https://www.conventionalcommits.org/en/v1.0.0/
