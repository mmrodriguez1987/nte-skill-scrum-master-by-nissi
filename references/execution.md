# Boards, assignment, and development progress

## Operational scope

When publishing a plan to a specified project, ensure a usable board exists and assign new items to the authenticated user. This is the skill's default behavior; do not ask again for necessary steps within an authorized publication. A proposal request or read-only mode does not publish or provision resources.

The project must be identified and already exist. Creating a project or organization, or changing its process, is not implied by creating a board. If several candidates exist, resolve them using IDs/configuration and scope; ask only if ambiguity remains. Do not treat a 403, an ambiguous 404, or an incomplete listing as proof of absence. Missing access requires reporting a blocker rather than duplicating resources.

## Ensure a board exists without duplication

1. Check the saved ID first, then paginate through candidate boards/teams. Verify the project, team, type, and filter/area scope; names alone are insufficient. Reuse the correct board.
2. If missing, record board creation and its dependencies in the manifest. Derive its name from the project/team unless an explicit name was provided. Do not create a board per story or sprint.
3. Execute the provider-specific sequence. Save filter, board, team, and area IDs as they become available. On timeout or conflict, query before retrying; preserve partial results.
4. Read back the configuration and check that planned items are eligible to appear. Tasks may appear on the sprint taskboard or beneath their stories rather than as cards on the main board.

### Jira

- Query the project's boards, their configuration, and filters. Reuse a Scrum board compatible with the requested scope. If only Kanban exists, do not convert or delete it; create a new Scrum board when appropriate for Scrum planning.
- For a new board, reuse a suitable saved filter or create one with JQL limited to the project and Rank ordering supported by the instance. Validate JQL and permissions; do not grant public access or modify others' filters.
- On Cloud, use `POST /rest/api/3/filter` when needed, followed by `POST /rest/agile/1.0/board` with `name`, `type: scrum`, `filterId`, and a project `location` when compatible. For Data Center, use supported API versions and its location contract. Do not assume boards can be created in any project type.
- Check the filter, location, user access, and issue eligibility. If team access requires sharing the filter, use only established project permissions/groups; if an appropriate access scope cannot be determined, report that step as pending.

### Azure DevOps

- Boards belong to teams. Query the configured team and its boards/backlogs; reuse the project's default team when appropriate. Do not invent a POST endpoint for creating an independent board.
- If the necessary team is missing, create it within the project using `POST /_apis/projects/{projectId}/teams?api-version=7.1` (or a supported version), then query the boards provisioned for it. This team creation is included in ensuring the board exists; it does not imply changing memberships or administrative permissions.
- Check/configure the team's area selection and iterations required by the plan while preserving other teams' settings. Do not assume REST team creation also created its own area or configured all defaults. Reuse a compatible area or create the minimum area required within the project for the requested board.
- If a feature is disabled or configuration permissions are missing, report the blocker. Do not change the process or repeatedly provision teams to bypass it.

## Identity and assignment

Resolve identity through the authenticated API, never from the token name, Git user, display name, or an assumed email. Record the identity ID with the destination and validate it again when resuming with different credentials.

- Jira Cloud: `GET /rest/api/3/myself`; use `accountId`. Assign through `fields.assignee.accountId` at creation when supported by the schema, or `PUT /rest/api/3/issue/{key}/assignee` with `{accountId: ...}`. Verify that the user is assignable in the project.
- Jira Data Center: `GET /rest/api/2/myself`; use `name`/the identifier supported by that version for assignment. Do not use the Cloud payload without checking compatibility.
- Azure DevOps: query the connection's authenticated identity (`GET /_apis/connectionData` when available) and resolve `authenticatedUser` to a valid project identity. Use its unique identifier and an identity value accepted by `System.AssignedTo`, not a display name alone. If the version does not support unambiguous identity resolution, stop assignment and explain the limitation.

Assign each newly created Epic, Feature, Story/PBI, Bug, and Task/Sub-task to the authenticated user when its type supports an assignee. For existing items managed by the plan, fill in missing assignees; preserve other people's assignments unless reassignment is explicitly requested. Do not change memberships or grant permissions to force assignment. On failure, mark the item's publication incomplete rather than claiming full success. Read back and compare the actual assignee ID.

## State progression

Discover states, categories, available transitions, required fields, and rules before moving items. Build a conceptual mapping such as the following; these names are examples rather than fields that must exist:

| Evidence | Task | Story/PBI |
|---|---|---|
| Selected, not started | To Do / New | To Do / New |
| Implementation actually started | In Progress / Active | In Progress / Active |
| Change ready and PR open | Review if available | Review or an equivalent open state |
| Task verified and its criteria met | Done when allowed by its workflow | Remains open while PR approval is missing |
| Acceptance criteria + Done + valid approval of required PRs | Done | Done / Closed according to workflow |
| Changes requested or approval invalidated | Resume affected work | Remains in or returns to the appropriate open state |

Update after actual milestones during development sessions and upon resumption; do not invent progress based on elapsed time. A task whose criteria include PR approval cannot close before that approval either. If Review does not exist, retain an appropriate open state and record the reason; do not create states or use a terminal state to represent waiting.

In Jira, query available transitions and use the transition ID with its required fields. In Azure, update `System.State` according to the workflow and use the current revision to detect conflicts. Moving a visual column is not necessarily a state change: also check column configuration when relevant.

Read the current state before each transition. If it already matches, skip the write. Record the item, previous/new state, evidence (commit/test/PR/review), timestamp, and result; verify afterward. On error, stop that transition and report the actual state. Do not produce duplicate comments for every query.

## Mandatory closure condition for User Stories/PBIs

1. Use one primary PR per story by default. Link it to the story and tasks; record the Git provider, repository, PR URL/ID, and current commit or iteration. Explicitly add required delivery PRs only when the scope needs several repositories or delivery branches. Verify the complete required set against acceptance criteria. A story without an associated PR remains pending: do not assume exceptions for documentation or small changes.
2. Verify acceptance criteria and the Definition of Done, including any existing project requirements for tests or integration.
3. Query the Git provider's reviews and policies. At least one actual approval must exist and required reviewers must be satisfied. Missing policies, green CI, positive comments, an open PR, or a bypass merge do not demonstrate approval. Do not approve your own PR or change policies to unlock closure.
4. Verify that approval still covers the current changes and no blocking change requests remain. Historical revoked, dismissed, or insufficient approvals do not count. New commits require checking review coverage and policies again; if the API cannot establish valid approval, keep the story open.
5. All required PRs must meet the condition. An abandoned PR or one closed without integration does not deliver the change; document its replacement and verify the PR that delivers it. A merged PR still requires evidence of approval; merged does not mean approved.
6. Follow [git-workflow.md](git-workflow.md) to collect provider-specific evidence and run `scripts/story_gate.py`. Immediately before the terminal transition, read PR heads and remote state again. Save approval evidence and verify the transition, including resolution/required fields where applicable. If the head/revision changes during verification, discard the evidence and reevaluate. A successful local check is not remote enforcement.

Approval is a necessary condition. A merge is not additionally required unless the project's Definition of Done or workflow requires it. This rule does not authorize approving, merging, or deploying changes.

Jira may link GitHub, Azure Repos, Bitbucket, or another provider: identify the actual provider and query its reviews. A Jira PAT does not grant repository access. For another host, use its authorized connector or credentials belonging to that host; never forward a Jira/Azure PAT to a different destination. If PR access is missing, record “pending approval verification” and keep the story open.

Tracking occurs while Claude executes or resumes the skill. A single run does not keep watching approvals after the session ends. Monitoring outside the session requires separately configured automation/webhooks; do not claim they exist or create them unless requested.

## Protect against premature automatic completion

Before starting linked development, inspect discoverable repository/workflow automation that can complete stories on commits, PR creation, merge, or completion of child tasks. Record observed behavior and any unknown configuration. Use neutral links in commits and PRs as specified in the Git workflow reference. Do not enable “Complete associated work items after merging”, `transitionWorkItems`, resolution mentions, Smart Commit transitions, or equivalent options for a story whose full closure gate has not passed.

A single primary PR still needs actual approval, acceptance, and Done; merge by bypass is insufficient. For several required PRs, merging one must not close the story while another remains unapproved. Avoid automatic closure from any one PR and perform the story transition only after checking the complete required set. Do not configure automation that closes a parent merely because its tasks are Done.

Existing automation may be administered by someone else. Do not silently disable repository-wide settings or modify shared workflows. If a conflicting rule cannot be safely avoided within authorized operations, report a closure-protection blocker and keep the story open. A strict guarantee outside the session requires a separately authorized provider-side validator/automation that evaluates the same condition; documentation and the local checker cannot enforce it against external actors.

At each managed milestone and resumption, reconcile terminal stories against the required evidence. If the skill's managed story was prematurely closed or its approval became invalid, use an authorized reopen transition where allowed, record the reason, and keep acceptance/PR evidence intact. If reopening is unavailable or outside the authorized scope, report the exact inconsistency rather than claiming protection succeeded. Do not repeatedly fight an external rule: stop conflicting state writes and surface the configuration conflict.

## Official sources

- Jira boards: https://developer.atlassian.com/cloud/jira/software/rest/api-group-board/
- Jira assignment: https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/
- Azure teams and boards: https://learn.microsoft.com/en-us/azure/devops/organizations/settings/add-teams
- Azure team creation: https://learn.microsoft.com/en-us/rest/api/azure/devops/core/teams/create?view=azure-devops-rest-7.1
- Azure Repos reviews: https://learn.microsoft.com/en-us/azure/devops/repos/git/review-pull-requests
- GitHub review validity: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
