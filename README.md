# Policy Enforcement Sentinel

*"Can you prevent people from doing XYZ in Databricks?"* 
Sometimes, the answer is: *"No, sorry, anyone with access can do that."*

When you are building out a complex architecture and who is allowed to do what in which environment is pretty complicated, it would benefit from a structured approach to documenting policies. Interoperability would be great, and maybe even a way to record who changed the policy and when.

Enter **Policy As Code**. 

The **Policy Enforcement Sentinel** is a reusable, standalone Databricks App designed exclusively for discovering resources across a Databricks workspace and evaluating them against Open Policy Agent (OPA) `.rego` policies.

---

## How It Works

The Sentinel operates mechanically at the workspace level in three phases:

1. **Phase 1: Discovery** On a configurable scheduled cadence, a background worker asynchronously loops through all assets in a workspace.
2. **Phase 2: Evaluation & Enforcement** The Sentinel evaluates each asset against your OPA policies. Based on the evaluation, what action do we take on a violation? Are we killing this on the spot? Are we flipping a tag or certification status?
3. **Phase 3: Notification** We notify the relevant parties. Maybe that's the governance team, maybe that's the policy violators directly.

### The action ladder

Every action a policy can ask for sits on one of four tiers. The tier, not the
action name, decides how hard it is to actually happen:

| Tier | Name | Actions | What it does |
|------|------|---------|--------------|
| 0 | Observe | `ALLOW`, `FLAG`, `PENDING_EXCEPTION`, `SKIPPED_ALLOWLIST` | Records a finding. Touches nothing. |
| 1 | Notify | `ANNOTATE`, `CERTIFY`, `WARN` | Tells someone. Reversible. |
| 2 | Restrict | `DISABLE`, `QUARANTINE`, `REVOKE_ACCESS`, `THROTTLE`, `UNCERTIFY` | Removes access or capability. Reversible, and every one of these can be undone from the audit trail. |
| 3 | Destructive | `DELETE`, `TERMINATE` | Irreversible. Deliberately the hardest thing to reach. |

All shipped policies request Tier 1 or Tier 2. Reaching for Tier 3 is a choice
you have to make explicitly, in a policy you write yourself.

### Scan modes

A run's mode sets the ceiling on what it may do. Anything a policy asks for
above the ceiling is downgraded to the highest permitted tier and recorded as
downgraded, so the finding is never silently lost:

1. **`audit`** (the default): everything is downgraded to Tier 0. Findings are
   recorded and nothing is touched. The dashboard offers a "Review and Act"
   button so you can execute a remediation yourself.
2. **`remediate`**: permits up to Tier 2. Reversible actions run automatically;
   destructive ones are downgraded.
3. **`enforce`**: permits Tier 3 as well — but only if every gate below also
   passes.

### The five gates

A Tier 3 action must clear all five. Any one of them failing downgrades the
action rather than blocking the run:

1. **`policy_declares_destructive`** — the policy must be explicitly annotated
   as destructive. An action that becomes destructive by accident cannot run.
2. **`enforcement_enabled`** — the global kill switch, off by default.
3. **`workspace_allowed`** — the workspace must be named in
   `DESTRUCTIVE_ACTION_WORKSPACES`, which is empty by default, meaning nowhere.
4. **`human_approval`** — a run-scoped approval naming the person who gave it.
   Approvals expire.
5. **`blast_radius`** — if a single run would destructively act on more
   resources than the configured limit, every Tier 3 action in the run is
   refused. This is the guard against a policy edit that unexpectedly matches
   everything.

Scheduled runs can never construct an approval, because there is nobody present
to name. So an unattended run in `enforce` mode still fails gate 4: raising a
schedule's mode widens what it may do as far as Tier 2, and Tier 3 stays out of
reach from the scheduler by construction.

### The Allowlist (Exceptions)

Not all rules can apply 100% of the time. The Sentinel includes an **Allowlist** feature to manage exceptions gracefully.

- **Adding Exceptions:** You can add an exception in the UI for a specific resource (e.g., `cluster-12345`) indicating why it is exempt from standard policies.
- **Evaluation:** During the discovery phase, the Sentinel pulls all active allowlist exceptions and injects them into the evaluation engine. 
- **Reprieve:** The Rego policies natively parse these exceptions. If a resource matches an approved exception, the policy drops its requested action to `SKIPPED_ALLOWLIST` and marks the resource as "in policy" due to an approved business exception.

---

## Writing Policies

Policies are evaluated using **Open Policy Agent (OPA)** and are written in **Rego**—a declarative language whose superpower is reusability (DRY not WET). The Sentinel passes the definition of each discovered workspace resource into OPA as a JSON payload, and OPA evaluates it against all `.rego` policies located in the `backend/policies` folder.

You can develop, test, and tweak these policies directly in the app's **Policy Editor** tab, which simulates the evaluation live.

### The policy assistant

Rego is not most people's first language, so the editor has an assistant behind
it (configurable in **Settings → Agent**, and switched off by disabling it
there). It drafts Rego from a description, answers questions about the policies
you already have, writes the notes on a pull request, and keeps a plain-English
translation of each policy alongside it in the repository.

The translation matters more than it sounds. It is committed in the same pull
request as the `.rego` file it describes, which means the reviewer who cannot
read Rego is still reviewing the change rather than approving it on trust.

### Policies live in git, and only in git

Policies are the rules that decide whether something gets touched, so their
history has to be the reviewable kind. Nothing in the app writes a policy to
disk. There is no Save button.

`backend/policies/` is a **working copy**, not storage. It is hydrated from your
GitHub branch at startup and refreshed every few minutes, and anything written
there by hand is replaced on the next sync. Treating it as durable would be a
mistake in production anyway: Databricks Apps have ephemeral filesystems, so a
saved file is gone at the next restart.

Every change, including creating and retiring a policy, goes through a pull
request:

1. **Read:** the Policy Editor shows the policy as it exists on your configured
   branch, so you are never editing stale code.
2. **Evaluate:** the Playground runs your draft against sample JSON input
   without committing anything.
3. **Propose:** "Open PR" cuts a branch, commits the `.rego` file together with
   its regenerated plain-English explanation, and opens a pull request. Drafts
   live in your browser until then, so a half-finished edit survives a reload
   without ever reaching the repository.
4. **Take effect:** once the PR merges, the next sync picks it up. No redeploy.

#### What happens if I don't configure GitHub?

The Policy Editor becomes read-only and says so. You can still read, evaluate,
and test policies; you just cannot change them, because there is nowhere safe to
put the change. The app runs whatever policies shipped in its bundle.

#### What do the actual Sentinel runs use?

The working copy — which is to say, the target branch as of the last sync. The
sync is what makes a merged PR take effect, so review is the gate on what runs,
not deployment.

If the policies directory is itself a git checkout, as it is when you run
locally from a clone, the sync leaves it alone rather than overwriting the work
in your tree.

To enable this, configure the following in your `.env` (for local dev) or `databricks.yml` (for production):

```yaml
env:
  - name: GITHUB_TOKEN
    value: "your-github-pat"
  - name: GITHUB_REPO
    value: "databricks-field-eng/policy-enforcement-sentinel"
  - name: GITHUB_TARGET_BRANCH
    value: "main"
  - name: GITHUB_POLICIES_DIR
    value: "backend/policies"
```

The token needs read and write access to repository contents and pull requests.
If your organisation enforces SAML single sign-on, the token must additionally
be authorised for that organisation, or every request will be refused with a
403 that has nothing to do with the token's permissions.

### Supported Resources

The Sentinel currently discovers and evaluates the following Databricks resources:
- Clusters
- Jobs
- SQL Warehouses
- Dashboards
- Service Principals
- Notebooks
- Volumes
- Tables
- Model Serving Endpoints
- Spark Declarative Pipelines

### Policy Example

A standard policy checks conditions and returns an action and severity. For example, ensuring all clusters have a `Team` tag:

```rego
package databricks.governance.cluster_tags

default is_violation = false
default action = "ALLOW"
default severity = "LOW"
default reason = "No issues found"

# Trigger a violation if the resource is a cluster and is missing custom_tags
is_violation {
  input.resource.type == "cluster"
  not input.resource.attributes.custom_tags
}

action = "WARN" { is_violation }
severity = "MEDIUM" { is_violation }
reason = "Cluster is missing required tags." { is_violation }
```

---

## Getting Started Locally

The project includes a unified development script that runs both the FastAPI backend and the React/Vite frontend.

### Prerequisites

- Node.js (for the frontend)
- Python 3.11+ (for the backend)
- Open Policy Agent (`opa`) CLI installed locally (e.g., `brew install opa` or the backend will attempt to download a static binary).

### 1. Environment Variables & Database

Create a `.env` file in the `backend/` directory by copying `.env.example`:

```bash
cp backend/.env.example backend/.env
```

Configure your Databricks workspace URL and authentication token inside. 

*Note: For local development, the app will automatically fall back to using a local SQLite database (`backend/sentinel.db`) to store run history and allowlist exceptions if no external database is configured.*

### 2. Start the Servers

Simply run the development shell script from the project root:

```bash
chmod +x dev.sh
./dev.sh
```

- **Frontend:** `http://localhost:5173`
- **Backend API:** `http://localhost:8000`

*Note: The script automatically provisions a Python virtual environment (`backend/venv`), installs dependencies, and runs `npm install` for the frontend.*

### Running the MCP Server

The FastMCP server is integrated directly into the FastAPI backend using Server-Sent Events (SSE). This means any external tool on the Databricks platform (or local agents) can connect to it seamlessly as long as the App is running.

You can connect an external AI agent (like Claude Desktop or Cursor) to the MCP Server at:
```
http://localhost:8000/mcp
```
*(Or your deployed Databricks App URL + `/mcp`)*

This exposes tools like `trigger_sentinel_run` natively without needing a separate `stdio` process.

---

## Deployment to Databricks

This repository is configured as a **Databricks Asset Bundle (DAB)**. The bundle handles automatically packaging the app and deploying it to your workspace.

### 1. Authenticate
Ensure your Databricks CLI is authenticated to your target workspace:
```bash
databricks auth profiles
databricks auth login -p myenv
```

### 2. Deploy & Run
To deploy the App and run it immediately (e.g. against your `dev` target using a specific CLI profile `myenv`):
```bash
databricks bundle deploy -t dev -p myenv && databricks bundle run policy-enforcement-sentinel -t dev -p myenv
```

### Cross-Workspace Scanning

The Sentinel can scan and enforce policies across multiple workspaces from a single Databricks App deployment. By default, it runs against the workspace it is deployed in (using the standard `DATABRICKS_HOST` and `DATABRICKS_TOKEN` variables). 

To configure multiple workspaces, set the `SENTINEL_WORKSPACES` environment variable as a JSON string containing an array of workspace configurations. When the background scheduler fires or a manual run is triggered, the Sentinel will iterate through every workspace in the list, compile all the violations, and display them in a single, unified view on the dashboard.

**Example `databricks.yml` configuration:**
```yaml
env:
  - name: SENTINEL_WORKSPACES
    value: '[{"name": "ws-enterprise-prod", "environment": "prod", "host": "https://prod.cloud.databricks.com", "token": "dapi123..."}, {"name": "ws-enterprise-dev", "environment": "dev", "host": "https://dev.cloud.databricks.com", "token": "dapi456..."}]'
```

*Note: If you use a Service Principal (OAuth M2M) with Account-level privileges, you can omit the `token` in the JSON and simply provide `client_id` and `client_secret` at the global level. The Sentinel will automatically authenticate against each `host` using those central credentials.*

### Automated Scheduling

The Sentinel doesn't require manual button-clicks. It has a built-in background scheduler that evaluates your workspace on a regular cadence using cron syntax.

The schedule, its workspace, its environment, and its mode are all editable in
**Settings → Scanning**, which validates the cron expression and shows the next
few times it would fire before you save. Changes take effect within a minute;
the worker re-reads the schedule as it runs, so there is no restart. Leaving the
schedule blank disables unattended scanning entirely, which is the default.

You can also set the same values as environment variables to establish the
deployment default, in `databricks.yml` or your local `.env`:

```yaml
env:
  - name: SENTINEL_CRON_SCHEDULE
    value: "0 2 * * *" # Run every day at 2:00 AM UTC
  - name: SENTINEL_CRON_WORKSPACE
    value: "ws-enterprise-prod"
  - name: SENTINEL_CRON_ENV
    value: "prod"
  - name: SENTINEL_CRON_MODE
    value: "audit" # "remediate" permits reversible actions
```

When configured, the FastAPI server spins up a background worker that monitors the time. When the cron schedule hits, it triggers a full workspace evaluation automatically. The results will seamlessly appear in the dashboard run history just like a manual trigger.

Note that `enforce` buys a scheduled run less than it appears to. Unattended
runs cannot produce a human approval, so they fail the approval gate and top out
at Tier 2 regardless.

### Service Principal Permissions

When running as a Databricks App in production, the App runs under the identity of a Service Principal. Note that the Service Principal needs wide-ranging permissions to discover and remediate resources across your workspace. Consider the blast radius and the **Principle of Least Privilege (PLP)**.

For example, to enforce actions, the Service Principal may need:
- `CAN_MANAGE` on Compute to kill non-compliant clusters.
- `BROWSE` or `USE_CATALOG` on Unity Catalog to inspect datasets.

---

## Extending the Sentinel

### Implementing Notification Providers

While the acting tiers (`CERTIFY`, `UNCERTIFY`, `REVOKE_ACCESS`, `TERMINATE` and the rest) interact directly with the Databricks SDK, the `WARN` action requires an external notification provider (like Email, Slack, Microsoft Teams, or Jira).

By default, the Sentinel includes an SMTP Email provider. When a policy evaluates to `WARN`, the Sentinel will look up the resource owner's email address and send them a warning notification.

**To configure the built-in Email Notifications:**
Update your `.env` or `databricks.yml` to include your SMTP settings. If no settings are provided, it defaults to a local Mailpit instance (`localhost:1025`) for local testing:

```yaml
env:
  - name: SMTP_SERVER
    value: "localhost"
  - name: SMTP_PORT
    value: "1025"
  - name: SMTP_USERNAME
    value: ""
  - name: SMTP_PASSWORD
    value: ""
  - name: SMTP_FROM_EMAIL
    value: "sentinel@databricks.com"
```

**To implement a custom provider (e.g., Slack):**
1. Create a new provider class in `backend/app/providers/notifications/`.
2. Update the `warn()` method inside the specific resource handlers (`backend/app/providers/databricks/handlers/*.py`) to instantiate and call your new provider instead of the default `EmailNotifier`.

---

## The Unvarnished Truth

- **Not a replacement for Unity Catalog:** If you can manage permissions and rules natively in Unity Catalog, prefer that over this!
- **Don't lock the platform down:** There is a reason we don't lock Databricks down completely — we want users to build stuff!
- **Reactive, not proactive:** Don't count on this for mission-critical security. It is a reactive audit and enforcement tool, meaning non-compliant resources may briefly exist before the next scheduled run remediates them.