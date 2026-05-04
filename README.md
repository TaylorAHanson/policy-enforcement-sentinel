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

### Audit (Dry Runs) vs. Enforcement (Full Runs)

The Sentinel has two operational modes to ensure you don't accidentally break critical infrastructure:

1. **Audit Only (Dry Run):** The default mode. The Sentinel discovers resources, evaluates them, logs all violations, and calculates the required actions (`KILL`, `WARN`, `CERTIFY`, `UNCERTIFY`). **It does not execute these actions.** Instead, the dashboard will show a "Review and Act" button next to each violation, allowing you to manually execute the remediation if you choose.
2. **Execute Enforcement:** This is the live mode. The Sentinel will automatically execute the required actions immediately against any non-compliant resources as soon as the policy evaluates them. This is a destructive operation and carries an "Are you sure?" modal in the UI.

### The Allowlist (Exceptions)

Not all rules can apply 100% of the time. The Sentinel includes an **Allowlist** feature to manage exceptions gracefully.

- **Adding Exceptions:** You can add an exception in the UI for a specific resource (e.g., `cluster-12345`) indicating why it is exempt from standard policies.
- **Evaluation:** During the discovery phase, the Sentinel pulls all active allowlist exceptions and injects them into the evaluation engine. 
- **Reprieve:** The Rego policies natively parse these exceptions. If a resource matches an approved exception, the policy overrides its standard destructive action (like `KILL`) and marks the resource as "in policy" due to an approved business exception.

---

## Writing Policies

Policies are evaluated using **Open Policy Agent (OPA)** and are written in **Rego**—a declarative language whose superpower is reusability (DRY not WET). The Sentinel passes the definition of each discovered workspace resource into OPA as a JSON payload, and OPA evaluates it against all `.rego` policies located in the `backend/policies` folder.

You can develop, test, and tweak these policies directly in the app's **Policy Editor** tab, which simulates the evaluation live.

### GitOps & GitHub Integration (Recommended)

To prevent split-brain scenarios and maintain a strict audit trail, the Sentinel supports a fully integrated GitOps workflow. By configuring a GitHub Personal Access Token (PAT), the Policy Editor transforms into a live authoring environment connected directly to your repository:

1. **Live Read:** The Policy Editor fetches the absolute latest `.rego` policies directly from your configured GitHub branch, ensuring you never edit stale code.
2. **Live Evaluation:** You can author and test policies instantly in the Playground against simulated JSON inputs without saving.
3. **Propose Changes:** Instead of saving locally, clicking "Create Pull Request" in the UI will automatically create a new branch, commit your changes, and open a Pull Request in GitHub for your team to review.
4. **Enforcement:** The Databricks App itself continues to enforce the physical policies deployed in its bundle. Once your PR is merged, your standard CI/CD pipeline deploys the updated app to Databricks, and the new policies take effect.

#### What happens if I don't configure GitHub?
The GitHub integration is purely optional for local development. If you omit the variables, the app gracefully falls back to reading and writing `.rego` files directly to the local disk (`backend/policies`).

However, **in a deployed Databricks App, you should always configure the GitHub integration.** Databricks Apps run in a containerized environment where the local filesystem is ephemeral. If you omit the GitHub variables in production, any policy changes saved from the UI will be lost the next time the app restarts.

#### What do the actual Sentinel runs use?
The actual enforcement engine (the background cron scheduler and the "Run Now" button) **always reads strictly from the physical local disk inside the container** (`backend/policies/*`). It **never** pulls live policies from GitHub during a run.

This creates a safe, conflict-free architecture:
- The **UI** connects to GitHub so users can author and test the absolute bleeding edge.
- The **Enforcement Engine** reads the local disk to run what has *actually been deployed* via your CI/CD pipeline.

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

If GitHub integration is not configured, the Policy Editor will gracefully fall back to reading and writing `.rego` files directly to the local disk.

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

**To configure the schedule:**
Update your `databricks.yml` to inject the environment variables for your deployed app, or set them in your local `.env` file:

```yaml
env:
  - name: SENTINEL_CRON_SCHEDULE
    value: "0 2 * * *" # Run every day at 2:00 AM UTC
  - name: SENTINEL_CRON_WORKSPACE
    value: "ws-enterprise-prod"
  - name: SENTINEL_CRON_ENV
    value: "prod"
  - name: SENTINEL_CRON_MODE
    value: "audit" # Use "enforce" for automated destructive actions
```

When configured, the FastAPI server spins up a background worker that monitors the time. When the cron schedule hits, it triggers a full workspace evaluation automatically. The results will seamlessly appear in the dashboard run history just like a manual trigger.

### Service Principal Permissions

When running as a Databricks App in production, the App runs under the identity of a Service Principal. Note that the Service Principal needs wide-ranging permissions to discover and remediate resources across your workspace. Consider the blast radius and the **Principle of Least Privilege (PLP)**.

For example, to enforce actions, the Service Principal may need:
- `CAN_MANAGE` on Compute to kill non-compliant clusters.
- `BROWSE` or `USE_CATALOG` on Unity Catalog to inspect datasets.

---

## Extending the Sentinel

### Implementing Notification Providers

While the destructive actions (`KILL`, `CERTIFY`, `UNCERTIFY`) interact directly with the Databricks SDK, the `WARN` action requires an external notification provider (like Email, Slack, Microsoft Teams, or Jira).

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