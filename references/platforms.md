# Integrations

For board creation/reuse, token owner identification, assignment, and state updates with PR approval required for closure, follow [execution.md](execution.md). The tracking platform and Git provider may differ.

## REST transport

`tracker_api.py` uses Python 3 and the standard library. Supported dotenv syntax includes `KEY=value`, single-line quoted values, and full-line comments. It does not interpret commands, variable expansion, or inline comments. The selected file must exist and its values are authoritative; they are not combined with inherited variables. Environment-only operation requires `--use-process-env`.

```bash
python3 <skill>/scripts/tracker_api.py --env-file <project>/.env check
python3 <skill>/scripts/tracker_api.py --env-file <project>/.env request --path '/rest/api/3/project/APP'
```

`request` accepts `--method GET|POST|PUT|PATCH`, `--body-file <json>`, and `--content-type <type>`. Methods other than GET require `--allow-write`, including POST queries. This flag prevents accidents; it does not establish human authorization.

Example for an authorized creation with an already prepared payload:

```bash
python3 <skill>/scripts/tracker_api.py --env-file <project>/.env request --method POST --path '/rest/api/3/issue' --body-file .scrum/create-issue.json --allow-write
```

The helper provides transport: Claude discovers metadata, prepares payloads, handles pagination, executes, and reconciles according to the skill. It does not automatically synchronize manifests. It returns status, data, and allowlisted operational headers for pagination, retry timing, and correlation. It exposes bounded, sanitized validation details from supported JSON errors rather than raw bodies. It does not retry. Do not include secrets in payloads or query strings; decoded JSON keys/values and decoded URLs are checked for configured credentials before transmission. Pagination cursors are operational metadata, not authentication credentials.

Read cursors from body fields such as `nextPageToken` or supported response headers as required by the endpoint. Stop only when the provider indicates the listing is complete. On 429 use retry metadata and a bounded retry plan; never retry a write with an uncertain outcome without reconciliation. Treat `Link` and other returned URLs as untrusted routing data: retain the configured host/base and validate the requested resource before following pagination.

Truncated or interrupted HTTP responses, including a broken response body after a successful creation status, produce a structured failure. A possibly sent write is reported with `outcome: unknown` and `reconcile_required: true`; search for its persistent marker before any retry. Partial response bytes are never included in diagnostics. A truncated GET is a read failure, not evidence that the resource is absent. These outcomes do not trigger automatic retries.

## Jira

- `jira-cloud`: Basic authentication with `JIRA_EMAIL` and `JIRA_API_TOKEN`. Scoped tokens may require the gateway and cloud ID; configure `JIRA_BASE_URL` for the token rather than assuming the site URL.
- `jira-dc`: Bearer authentication with `JIRA_PAT`; the base URL may include a context such as `/jira`. Check the instance version.

Query identity, project, types, creation metadata, fields, workflow, and Scrum board. Paginate issues and sprints. Cloud uses platform REST v3 and Jira Software REST as appropriate; Data Center requires compatibility with its version, usually platform v2. Cloud rich text may require Atlassian Document Format.

Do not assume a Feature level between Epic and Story; discover the actual hierarchy and relationships/fields. Story and Task may be peers; use available subtasks for child work. If a level is missing, propose grouping and explain its limitations without changing site configuration.

For planning, identify the board ID, estimation field, existing sprints, and permissions. Creating a sprint and moving issues are separate operations: verify both. Creating does not mean starting. Do not copy field IDs from another project.

Official sources:
- https://developer.atlassian.com/cloud/jira/platform/basic-auth-for-rest-apis/
- https://confluence.atlassian.com/enterprise/using-personal-access-tokens-1026032365.html
- https://developer.atlassian.com/cloud/jira/platform/rest/v3/
- https://developer.atlassian.com/cloud/jira/software/rest/api-group-sprint/

## Azure DevOps

Configure the organization/collection URL, project, team when applicable, and `AZURE_DEVOPS_AUTH_MODE`. Use `pat` with `AZURE_DEVOPS_PAT` (Basic, empty username) or `access-token` with `AZURE_DEVOPS_ACCESS_TOKEN` (Bearer). Only the selected credential is used. Read [git-workflow.md](git-workflow.md) for the separate Git PAT and review evidence. Check Work Items permissions and any additional permissions needed to administer iterations when required by the task.

Discover types, fields/rules, team backlog configuration, areas, iterations, dates, and capacity. A list of types alone does not establish the hierarchy.

- Agile: Epic → Feature → User Story → Task.
- Scrum: Epic → Feature → Product Backlog Item → Task.
- Basic, CMMI, or customized processes: adapt to the observed schema.
- Bug occupies the level configured by the team; do not force it beneath a story.

Initial query: `/{project}/_apis/wit/workitemtypes?api-version=7.1`. Encode path segments. Services supports 7.1; Server may require a different version (`AZURE_DEVOPS_API_VERSION`).

Creating/updating Work Items uses JSON Patch (`application/json-patch+json`). Build parent/child links using relations and the actual parent URL. Query internal field names for estimation, acceptance criteria, area, and iteration rather than inferring them from display labels. Use the current revision to detect conflicts.

A project iteration, its selection by a team, and an item's `IterationPath` are separate settings. Reuse iterations when appropriate. Create iterations/change dates only when included in the task. Verify the team, iteration, and items before claiming the sprint is planned.

Official sources:
- https://learn.microsoft.com/en-us/azure/devops/boards/backlogs/define-features-epics
- https://learn.microsoft.com/en-us/azure/devops/organizations/accounts/use-personal-access-tokens-to-authenticate
- https://learn.microsoft.com/en-us/rest/api/azure/devops/wit/work-item-types/list?view=azure-devops-rest-7.1
- https://learn.microsoft.com/en-us/rest/api/azure/devops/wit/work-items/create?view=azure-devops-rest-7.1

## Other providers

Preserve the conceptual backlog and add an adapter based on the provider's actual API, authentication, and hierarchy. Do not send a Jira/Azure PAT to another provider. Explain what is implemented and what needs additional support.
