# Policy Enforcement Sentinel

*"Can you prevent people from doing XYZ in Databricks?"* 
Usually, the answer is: *"No, sorry, anyone with access can do that."*

When you are building out a complicated architecture and who is allowed to do what in which environment is pretty complicated, it would benefit from a structured approach to documenting policies. Interoperability would be great, and maybe even a way to record who changed the policy and when.

Enter **Policy As Code**. This is a magic phrase. When you say this phrase to an enterprise architect or security architect, they go bananas. *Coocoo for Cocoa Puffs.* And for good reason.

The **Policy Enforcement Sentinel** is a reusable, standalone Databricks App designed exclusively for discovering resources across a Databricks workspace and evaluating them against Open Policy Agent (OPA) `.rego` policies.

### The Mechanics

- **OPA (Open Policy Agent):** Takes a policy in one hand, a set of facts in the other, smooshes them together, and returns "yes" or "no". Think of it as a boolean evaluation engine.
- **Rego:** The declarative language the policy is written in. Its superpower? Inheritance, Reusability, DRY (Don't Repeat Yourself).

### How the Sentinel Works

The Sentinel operates mechanically at the workspace level in three phases:

1. **Phase 1: Discovery** On a configurable scheduled cadence, a background worker asynchronously loops through all assets in a workspace and applies each policy to each asset.
2. **Phase 2: Enforcement** Are we killing this on the spot? Are we flipping a tag or certification status? What action do we take on violation?
3. **Phase 3: Notification** We notify the relevant parties. Maybe that's the governance team, maybe that's the policy violators directly.

### The Unvarnished Truth

- **Not a replacement for Unity Catalog:** If you can manage it in Unity Catalog, prefer that!
- **Don't lock the platform down:** There is a reason we don't lock Databricks down completely—we want users to build stuff!
- **Reactive, not proactive:** Don't count on this for mission-critical security. It is a reactive audit and enforcement tool.

---

## Dessert Menu (Features)

- **Blazing Fast Evaluation:** Discovers resources (Compute, Jobs, Genies, Apps, etc.) and evaluates them concurrently.
- **OPA Playground:** A dedicated UI (`/policies`) for authoring Rego policies, simulating JSON inputs, and testing outputs in real-time.
- **MCP Server Included:** Add it to Genie or external AI agents! Runs a FastMCP server to expose policy enforcement and testing tools.
- **Lifecycle Integration:** Can be used in 3 layers of the lifecycle: request, provision, and monitor.

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
Once deployed, the app will execute `python backend/run.py` to start the web server. The environment variables required for Databricks SDK authentication are natively injected by the Databricks Apps runtime. Note: The Service Principal this runs as needs wide-ranging permissions - consider the blast radius and Principle of Least Privilege (PLP).
