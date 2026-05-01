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

This repository is configured as a **Databricks Asset Bundle (DAB)**. By default, the bundle specifies how the app is deployed to your workspace. 

Ensure your Databricks CLI is authenticated:
```bash
databricks auth login
```

To deploy to your personal development workspace (e.g., `local` target):
```bash
databricks bundle deploy
```

To deploy to production:
```bash
databricks bundle deploy -t prod
```

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

## The Unvarnished Truth

- **Not a replacement for Unity Catalog:** If you can manage permissions and rules natively in Unity Catalog, prefer that over this!
- **Don't lock the platform down:** There is a reason we don't lock Databricks down completely — we want users to build stuff!
- **Reactive, not proactive:** Don't count on this for mission-critical security. It is a reactive audit and enforcement tool, meaning non-compliant resources may briefly exist before the next scheduled run remediates them.