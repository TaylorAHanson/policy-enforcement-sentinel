import json
import logging
import os
import shutil
import subprocess
from typing import Any, Dict, Optional

import httpx

from app.core.exceptions import PermanentError, RetryableError
from app.providers.base import BaseProvider

logger = logging.getLogger(__name__)

OPA_SETUP_HINT = (
    "Open Policy Agent (opa) is not available. Install it (e.g. `brew install opa`) so `opa` is on PATH, "
    "or set OPA_BINARY_PATH in .env to the executable, or set OPA_URL to a running OPA server "
    "that already has your Rego bundles loaded. See https://www.openpolicyagent.org/docs/latest/"
)


class OpaProvider(BaseProvider):
    """
    Provider for evaluating Open Policy Agent (OPA) Rego policies.
    It can be configured to use a remote OPA server via REST or a local OPA binary.
    """
    def __init__(self, config: dict = None):
        super().__init__(config)
        # Check if we should use a remote server (e.g. http://opa:8181)
        self.opa_url = self.config.get("opa_url")
        self.use_local_binary = self.config.get("use_local_binary", True)
        self.policies_dir = self.config.get("policies_dir", "policies")
        self.opa_binary = self.config.get("opa_binary")

    def _resolve_opa_executable(self) -> Optional[str]:
        """Return path to the OPA CLI, or None if not found."""
        configured = (self.opa_binary or "").strip() if self.opa_binary else ""
        if configured:
            expanded = os.path.expanduser(configured)
            if os.path.isfile(expanded):
                return expanded
            logger.warning(f"Configured OPA path {expanded} is not a file.")
            return None
            
        # 1. Try to find a bundled binary first (e.g. backend/bin/opa_linux_amd64)
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        bundled_linux = os.path.join(base_dir, "bin", "opa_linux_amd64")
        
        if os.path.isfile(bundled_linux):
            # Check if it's already executable
            if os.access(bundled_linux, os.X_OK):
                return bundled_linux
                
            # If not executable, it might be in a read-only filesystem (Databricks Apps)
            # Copy it to /tmp and make it executable there
            dest_path = "/tmp/opa_linux_amd64"
            try:
                import stat
                if not os.path.exists(dest_path):
                    shutil.copy2(bundled_linux, dest_path)
                else:
                    if os.path.getsize(bundled_linux) != os.path.getsize(dest_path):
                        shutil.copy2(bundled_linux, dest_path)
                        
                st = os.stat(dest_path)
                os.chmod(dest_path, st.st_mode | stat.S_IEXEC)
                if os.access(dest_path, os.X_OK):
                    return dest_path
                else:
                    logger.error(f"Failed to verify executable permissions on {dest_path} after chmod.")
            except Exception as e:
                logger.warning(f"Failed to copy and make {bundled_linux} executable in /tmp: {e}")
        else:
            # 1.5. Fallback: If not found, try downloading it to /tmp
            import platform
            os_name = platform.system().lower()
            arch_name = platform.machine().lower()
            dest_path = f"/tmp/opa_{os_name}_{arch_name}"
            
            if os.path.isfile(dest_path) and os.access(dest_path, os.X_OK):
                return dest_path
                
            logger.info(f"Bundled OPA binary not found. Downloading dynamically to {dest_path}...")
            try:
                import stat
                import urllib.request
                import platform
                
                # Determine OS and Architecture
                os_name = platform.system().lower()
                arch_name = platform.machine().lower()
                
                if os_name == "darwin":
                    opa_os = "darwin"
                else:
                    opa_os = "linux"
                    
                if arch_name in ["aarch64", "arm64"]:
                    opa_arch = "arm64_static"
                else:
                    opa_arch = "amd64_static"
                    
                opa_url = f"https://openpolicyagent.org/downloads/v0.61.0/opa_{opa_os}_{opa_arch}"
                logger.info(f"Downloading OPA from {opa_url}")
                urllib.request.urlretrieve(opa_url, dest_path)
                
                st = os.stat(dest_path)
                os.chmod(dest_path, st.st_mode | stat.S_IEXEC)
                
                if os.access(dest_path, os.X_OK):
                    logger.info(f"Successfully downloaded and prepared OPA at {dest_path}")
                    return dest_path
                else:
                    logger.error(f"Failed to make downloaded OPA executable.")
            except Exception as e:
                logger.warning(f"Failed to dynamically download OPA: {e}")
            
        # 2. Try looking in the system PATH
        found = shutil.which("opa")
        if found:
            return found
            
        logger.error("Could not resolve OPA executable by any method.")
        return None

    def _require_local_opa(self) -> str:
        exe = self._resolve_opa_executable()
        if not exe:
            raise PermanentError(OPA_SETUP_HINT)
        return exe

    def health_check(self) -> bool:
        if self.opa_url:
            try:
                response = httpx.get(f"{self.opa_url}/health")
                return response.status_code == 200
            except Exception:
                return False
        elif self.use_local_binary:
            return self._resolve_opa_executable() is not None
        return False

    async def check(self, policy_name: str, content: str) -> Dict[str, Any]:
        """
        Validate Rego syntax using `opa check`.
        By copying the policies directory to a temp dir and overwriting the specific policy,
        we can resolve imports correctly.
        """
        import tempfile
        if self.opa_url:
            # For remote servers, we might not have a direct check endpoint that accepts raw text easily without a PUT to a policy.
            try:
                opa_exe = self._require_local_opa()
            except PermanentError:
                return {"valid": True, "errors": []} # Can't check remotely easily without modifying server state
        else:
            opa_exe = self._require_local_opa()

        policies_dir_path = os.path.join(os.getcwd(), self.policies_dir)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            if os.path.exists(policies_dir_path):
                shutil.copytree(policies_dir_path, temp_dir, dirs_exist_ok=True)
            
            temp_policy_path = os.path.join(temp_dir, policy_name)
            with open(temp_policy_path, "w") as f:
                f.write(content)

            try:
                cmd = [opa_exe, "check", temp_dir, "-f", "json"]
                process = subprocess.run(cmd, capture_output=True, text=True)
                
                if process.returncode == 0:
                    return {"valid": True, "errors": []}
                else:
                    try:
                        output = json.loads(process.stdout)
                        errors = []
                        for err in output.get("errors", []):
                            msg = err.get("message", "Unknown error")
                            file_loc = err.get("location", {}).get("file", "")
                            # Only show errors for the file we are editing, or global errors
                            if not file_loc or policy_name in file_loc:
                                row = err.get("location", {}).get("row", "?")
                                errors.append(f"{msg} (Line {row})")
                        
                        # If errors were found but they were all in other files (unlikely since we just changed one),
                        # or if we couldn't parse properly, just return generic if empty
                        if not errors:
                             errors = ["Validation failed (check other files)."]
                        return {"valid": False, "errors": errors}
                    except:
                        return {"valid": False, "errors": [process.stderr or process.stdout or "Invalid Rego syntax"]}
            except Exception as e:
                return {"valid": False, "errors": [str(e)]}

    async def evaluate_content(self, policy_name: str, content: str, query: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate a Rego policy using live content from the editor instead of the saved file.
        """
        if self.opa_url:
            # We cannot easily push live content to a remote OPA server without modifying its state.
            # Fall back to evaluating whatever is already there.
            return await self._evaluate_remote(query, input_data)
        elif self.use_local_binary:
            return await self._evaluate_local_content(policy_name, content, query, input_data)
        else:
            raise PermanentError("OPA provider not configured for remote or local execution")

    async def _evaluate_local_content(self, policy_name: str, content: str, query: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        import tempfile
        opa_exe = self._require_local_opa()
        policies_dir_path = os.path.join(os.getcwd(), self.policies_dir)

        with tempfile.TemporaryDirectory() as temp_dir:
            # Copy all policies so imports work
            if os.path.exists(policies_dir_path):
                shutil.copytree(policies_dir_path, temp_dir, dirs_exist_ok=True)
            
            # Overwrite the specific policy with live content
            temp_policy_path = os.path.join(temp_dir, policy_name)
            with open(temp_policy_path, "w") as f:
                f.write(content)

            # Write input data
            temp_in_path = os.path.join(temp_dir, "input.json")
            with open(temp_in_path, "w") as temp_in:
                json.dump(input_data, temp_in)

            try:
                cmd = [
                    opa_exe,
                    "eval",
                    "-d",
                    temp_dir,
                    "-i",
                    temp_in_path,
                    "-f",
                    "values",
                    query,
                ]

                process = subprocess.run(cmd, capture_output=True, text=True)
                
                if process.returncode != 0:
                    raise PermanentError(f"OPA evaluation failed:\n{process.stderr or process.stdout}")
                    
                output = json.loads(process.stdout)
                if not output:
                    return {}
                return output[0] if isinstance(output, list) else output
            except FileNotFoundError as e:
                raise PermanentError(OPA_SETUP_HINT) from e

    async def evaluate(self, policy_path: str, query: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate a Rego policy.
        
        :param policy_path: Path to the .rego file or package name.
        :param query: The data path to query (e.g., "data.databricks.governance.asset_allowlist").
        :param input_data: The input dictionary to provide to OPA.
        :return: The evaluation result.
        """
        if self.opa_url:
            return await self._evaluate_remote(query, input_data)
        elif self.use_local_binary:
            return await self._evaluate_local(policy_path, query, input_data)
        else:
            raise PermanentError("OPA provider not configured for remote or local execution")

    async def _evaluate_remote(self, query: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        endpoint = f"{self.opa_url}/v1/data/{query.replace('data.', '').replace('.', '/')}"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(endpoint, json={"input": input_data})
                response.raise_for_status()
                return response.json().get("result", {})
        except httpx.RequestError as e:
            raise RetryableError(f"Failed to communicate with OPA server: {str(e)}")
        except httpx.HTTPStatusError as e:
            raise PermanentError(f"OPA server returned error: {e.response.text}")

    async def _evaluate_local(self, policy_file: str, query: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        import tempfile

        opa_exe = self._require_local_opa()

        policies_dir_path = os.path.join(os.getcwd(), self.policies_dir)
        if not os.path.exists(policies_dir_path):
            raise PermanentError(f"Policies directory not found: {policies_dir_path}")

        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as temp_in:
            json.dump(input_data, temp_in)
            temp_in_path = temp_in.name

        try:
            cmd = [
                opa_exe,
                "eval",
                "-d",
                policies_dir_path,
                "-i",
                temp_in_path,
                "-f",
                "values",
                query,
            ]

            try:
                process = subprocess.run(cmd, capture_output=True, text=True)
            except FileNotFoundError as e:
                raise PermanentError(OPA_SETUP_HINT) from e

            if process.returncode != 0:
                raise PermanentError(f"OPA evaluation failed: {process.stderr}")
                
            output = json.loads(process.stdout)
            if not output:
                return {}
            # Output is typically a list of results, we want the first one
            return output[0] if isinstance(output, list) else output

        finally:
            if os.path.exists(temp_in_path):
                os.remove(temp_in_path)
