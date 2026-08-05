#!/bin/bash

# Development script to run both frontend and backend concurrently
# Usage: ./dev.sh [--debug]

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Parse arguments
DEBUG_MODE=false
for arg in "$@"; do
    if [ "$arg" == "--debug" ]; then
        DEBUG_MODE=true
        echo -e "${YELLOW}Debug mode enabled${NC}"
    fi
done

# Function to cleanup background processes on exit
cleanup() {
    echo -e "\n${YELLOW}Shutting down services...${NC}"
    if [ ! -z "$FRONTEND_PID" ]; then
        kill $FRONTEND_PID 2>/dev/null || true
    fi
    if [ ! -z "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null || true
    fi
    wait $FRONTEND_PID $BACKEND_PID 2>/dev/null || true
    echo -e "${GREEN}Services stopped.${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Policy Enforcement Sentinel Dev Env   ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}\n"

# Clean up old log files
echo -e "${CYAN}Cleaning up old log files...${NC}"
rm -f backend.log frontend.log
echo -e "${GREEN}✓ Log files cleared${NC}"

# Check and kill processes on ports 8000 and 5173
echo -e "${CYAN}Checking for processes on ports 8000 and 5173...${NC}"
BACKEND_PORT_PID=$(lsof -ti:8000 2>/dev/null || true)
FRONTEND_PORT_PID=$(lsof -ti:5173 2>/dev/null || true)

if [ ! -z "$BACKEND_PORT_PID" ]; then
    echo -e "${YELLOW}Killing process on port 8000 (PID: $BACKEND_PORT_PID)...${NC}"
    kill -9 $BACKEND_PORT_PID 2>/dev/null || true
    sleep 1
fi

if [ ! -z "$FRONTEND_PORT_PID" ]; then
    echo -e "${YELLOW}Killing process on port 5173 (PID: $FRONTEND_PORT_PID)...${NC}"
    kill -9 $FRONTEND_PORT_PID 2>/dev/null || true
    sleep 1
fi

echo -e "${GREEN}✓ Ports cleared/available${NC}\n"

if [ ! -f "backend/.env" ]; then
    echo -e "${YELLOW}⚠ Warning: backend/.env file not found. Creating empty one...${NC}"
    touch backend/.env
fi

PYTHON_CMD="python3"
UVICORN_CMD=""
VENV_PATH=""

find_venv_python() {
    local venv_path=$1
    local python_exe=""
    if [ -f "$venv_path/bin/python" ] && [ -x "$venv_path/bin/python" ]; then
        python_exe="$venv_path/bin/python"
    elif [ -f "$venv_path/bin/python3" ] && [ -x "$venv_path/bin/python3" ]; then
        python_exe="$venv_path/bin/python3"
    fi
    if [ ! -z "$python_exe" ] && $python_exe --version > /dev/null 2>&1; then
        echo "$python_exe"
    else
        echo ""
    fi
}

VENV_PYTHON=""
if [ -d "backend/venv" ]; then
    VENV_PYTHON=$(find_venv_python "backend/venv")
    if [ ! -z "$VENV_PYTHON" ]; then
        echo -e "${CYAN}Using Python virtual environment (backend/venv)...${NC}"
        PYTHON_CMD="$VENV_PYTHON"
        VENV_PATH="backend/venv"
        UVICORN_CMD="$PYTHON_CMD -m uvicorn"
    fi
fi

if [ -z "$VENV_PYTHON" ]; then
    echo -e "${YELLOW}No valid virtual environment found. Creating one...${NC}"
    cd backend
    python3 -m venv venv
    sleep 1
    VENV_PYTHON=$(find_venv_python "venv")
    if [ -z "$VENV_PYTHON" ]; then
        echo -e "${RED}✗ Failed to create virtual environment${NC}"
        exit 1
    fi
    PYTHON_CMD="backend/$VENV_PYTHON"
    VENV_PATH="backend/venv"
    UVICORN_CMD="$PYTHON_CMD -m uvicorn"
    cd ..
fi

echo -e "${CYAN}Checking if dependencies are installed...${NC}"
MISSING_DEPS=()

if ! $PYTHON_CMD -c "import uvicorn" 2>/dev/null; then MISSING_DEPS+=("uvicorn"); fi
if ! $PYTHON_CMD -c "import fastapi" 2>/dev/null; then MISSING_DEPS+=("fastapi"); fi
if ! $PYTHON_CMD -c "import tenacity" 2>/dev/null; then MISSING_DEPS+=("tenacity"); fi
if ! $PYTHON_CMD -c "import sqlalchemy" 2>/dev/null; then MISSING_DEPS+=("sqlalchemy"); fi

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    echo -e "${YELLOW}Missing dependencies: ${MISSING_DEPS[*]}. Installing...${NC}"
    cd backend
    LOCAL_PYTHON_CMD="${PYTHON_CMD#backend/}"
    $LOCAL_PYTHON_CMD -m pip install --upgrade pip > /dev/null 2>&1
    $LOCAL_PYTHON_CMD -m pip install -r ../requirements.txt
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Dependencies installed${NC}"
    else
        echo -e "${RED}✗ Failed to install dependencies${NC}"
        exit 1
    fi
    cd ..
else
    echo -e "${GREEN}✓ Dependencies are installed${NC}"
fi

echo -e "${GREEN}→ Starting backend API...${NC}"
cd backend
if [[ "$UVICORN_CMD" == backend/* ]]; then
    LOCAL_UVICORN_CMD="${UVICORN_CMD#backend/}"
else
    LOCAL_UVICORN_CMD="$UVICORN_CMD"
fi

if [[ "$PYTHON_CMD" == backend/* ]]; then
    LOCAL_PYTHON_CMD="${PYTHON_CMD#backend/}"
else
    LOCAL_PYTHON_CMD="$PYTHON_CMD"
fi

echo "=== Backend started at $(date) ===" > ../backend.log

# Local-dev preflight: report config health and, where Databricks credentials
# are missing from backend/.env, resolve them from your own CLI login and export
# them so the backend runs as you. Also exports credentials that *are* in .env,
# because pydantic loads that file into the settings object rather than into the
# environment — so without this, anything building a bare WorkspaceClient()
# authenticates as whatever ~/.databrickscfg names as DEFAULT.
#
# stdout carries `export KEY=...` lines, which are eval'd here. The report goes
# to stderr and straight to your terminal. No-ops on a deployed runtime.
if [ -f "scripts/local_dev_preflight.py" ]; then
    PREFLIGHT_EXPORTS=$($LOCAL_PYTHON_CMD scripts/local_dev_preflight.py --export)
    if [ ! -z "$PREFLIGHT_EXPORTS" ]; then
        eval "$PREFLIGHT_EXPORTS"
    fi
fi

if [ "$DEBUG_MODE" = true ]; then
    $LOCAL_PYTHON_CMD -m pip install debugpy
    $LOCAL_PYTHON_CMD -m debugpy --listen 0.0.0.0:5678 -m uvicorn app.main:app --reload --port 8000 >> ../backend.log 2>&1 &
else
    $LOCAL_UVICORN_CMD app.main:app --reload --port 8000 >> ../backend.log 2>&1 &
fi
BACKEND_PID=$!
cd ..

sleep 3
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo -e "${RED}✗ Backend failed to start.${NC}"
    exit 1
fi

if [ ! -d "node_modules" ]; then
    echo -e "${CYAN}Installing node modules...${NC}"
    npm install
fi

echo -e "${GREEN}→ Starting frontend...${NC}"
echo "=== Frontend started at $(date) ===" > frontend.log
npm run dev >> frontend.log 2>&1 &
FRONTEND_PID=$!

sleep 3
if ! kill -0 $FRONTEND_PID 2>/dev/null; then
    echo -e "${RED}✗ Frontend failed to start.${NC}"
    kill $BACKEND_PID 2>/dev/null || true
    exit 1
fi

echo -e "\n${GREEN}✓ Development environment is running!${NC}\n"
echo -e "${CYAN}Frontend:${NC}  ${BLUE}http://localhost:5173${NC}"
echo -e "${CYAN}Backend API:${NC} ${BLUE}http://localhost:8000${NC}"
echo -e "${CYAN}API Docs:${NC}   ${BLUE}http://localhost:8000/docs${NC}"
echo -e "\n${YELLOW}Press Ctrl+C to stop all services${NC}\n"

wait $FRONTEND_PID $BACKEND_PID
