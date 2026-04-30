# Policy Enforcement Sentinel

The **Policy Enforcement Sentinel** is a standalone, high-performance Databricks App designed exclusively for discovering resources across a Databricks workspace and evaluating them against Open Policy Agent (OPA) `.rego` policies. 

By removing complex Agent architectures and state machines, the Sentinel operates extremely quickly with fully parallelized discovery and policy evaluation loops.

## Key Features

- **Blazing Fast Evaluation:** Discovers resources (Compute, Jobs, Genies, Apps, etc.) and evaluates them concurrently.
- **OPA Playground:** A dedicated 3-pane UI (`/policies`) for authoring Rego policies, simulating JSON inputs, and testing outputs in real-time.
- **MCP Server:** Runs a FastMCP server to expose policy enforcement and testing tools to external AI agents.
- **Dashboard:** A clear view of run histories, violation metrics, and categorized remediation actions (e.g., WARN, KILL, CERTIFY).

---

## Local Development

The project includes a unified development script that runs both the FastAPI backend and the React/Vite frontend.

### Prerequisites

- Node.js (for the frontend)
- Python 3.10+ (for the backend)
- Open Policy Agent (`opa`) CLI installed locally (e.g., `brew install opa` or it will attempt to download a static binary).

### 1. Environment Variables
Create a `.env` file in the `backend/` directory:

```env
# backend/.env
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
DATABRICKS_TOKEN=your_personal_access_token

# Or use Service Principal credentials
# DATABRICKS_CLIENT_ID=...
# DATABRICKS_CLIENT_SECRET=...
```

### 2. Start the Servers
Simply run the development shell script from the project root:

```bash
chmod +x dev.sh
./dev.sh
```

- **Frontend:** http://localhost:5173
- **Backend API:** http://localhost:8000
- **API Docs:** http://localhost:8000/docs

*Note: The script automatically provisions a Python virtual environment (`backend/venv`), installs dependencies, and runs `npm install` for the frontend.*

---

## Running the MCP Server

You can expose the Sentinel's capabilities to Claude Desktop or Cursor by running the FastMCP server. It operates over `stdio`:

```bash
cd backend
source venv/bin/activate
python run_mcp.py
```

This exposes tools like `trigger_sentinel_run` to external agents.

---

## Pushing to Databricks

This repository is configured as a **Databricks Asset Bundle (DAB)**. 

### 1. Configuration
Review `databricks.yml`. By default, the bundle specifies how the app is deployed to your workspace. Ensure your Databricks CLI is authenticated:

```bash
databricks auth login
```

### 2. Deploying
To deploy the app to your personal development workspace (e.g., `local` target):

```bash
databricks bundle deploy
```

To deploy to production:

```bash
databricks bundle deploy -t prod
```

### 3. Running in Databricks
Once deployed, the app will execute `python backend/run.py` to start the web server. The environment variables required for Databricks SDK authentication are natively injected by the Databricks Apps runtime.

---

## Writing Policies

Policies are written in standard Rego and should be placed in the `backend/policies` folder (or authored directly via the UI). 

A policy must be in the `databricks.governance.<policy_name>` package and ideally define:
- `is_violation`: Boolean
- `action`: String (e.g., "KILL", "WARN", "CERTIFY")
- `severity`: String (e.g., "HIGH", "LOW")
- `reason`: String explaining the violation.

Check the **Quick Reference** tab in the UI for exact schema examples and testing guidelines.