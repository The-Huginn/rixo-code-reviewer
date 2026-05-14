import json
import asyncio
import logging
import re
from typing import Type, Optional, List
from uuid import uuid4

from pydantic import BaseModel
from src.config import config

logger = logging.getLogger(__name__)


class CriticalAPIError(Exception):
    """Raised when Claude API returns a critical error that should NOT be gracefully degraded.

    These errors indicate systemic problems (auth, rate limiting, server errors)
    that should fail the review process rather than silently approving PRs.
    """
    pass


class ClaudeCodeClient:

    @staticmethod
    def generate_session_id() -> str:
        return str(uuid4())

    async def structured_completion(
            self,
            system_message: str,
            user_message: str,
            response_schema: Type[BaseModel],
            session_id: Optional[str] = None,
            allowed_tools: Optional[List[str]] = None,
            base_session_id: Optional[str] = None,
            model: Optional[str] = None
    ) -> BaseModel:
        if session_id is None:
            session_id = self.generate_session_id()

        prompt = self._build_prompt(system_message, user_message, response_schema)
        cmd = self._build_command(session_id, base_session_id, allowed_tools, prompt, model)

        # Log command details for debugging (excluding the full prompt for brevity)
        cmd_without_prompt = [c for c in cmd if c != prompt]
        logger.debug(f"Executing Claude CLI: {' '.join(cmd_without_prompt)} -p <prompt[{len(prompt)} chars]>")
        if base_session_id:
            logger.debug(f"Forking from base session: {base_session_id}")
        logger.debug(f"Session ID: {session_id}, Allowed tools: {allowed_tools}")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            timeout = config.ai.claude_cli_timeout
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)

            if stderr:
                logger.warning(f"Claude CLI stderr: {stderr.decode()[:500]}")

            stdout_str = stdout.decode() if stdout else ""

            # Parse CLI response even on non-zero exit code to check for API errors
            cli_response = None
            try:
                cli_response = json.loads(stdout_str) if stdout_str.strip() else None
            except json.JSONDecodeError:
                pass

            # Check for critical API errors in the response (even with exit code 0)
            if cli_response and cli_response.get("is_error"):
                result_content = cli_response.get("result", "")
                self._check_for_critical_error(result_content, session_id)

            if process.returncode != 0:
                error_msg = f"Claude CLI failed with exit code {process.returncode}\n"
                error_msg += f"stderr: {stderr.decode() if stderr else '(empty)'}\n"
                error_msg += f"stdout: {stdout_str[:1000] if stdout_str else '(empty)'}\n"
                error_msg += f"command: {' '.join(cmd[:10])}..."
                logger.error(error_msg)

                # Check if stdout contains API error info
                if cli_response and cli_response.get("result"):
                    self._check_for_critical_error(cli_response["result"], session_id)

                raise RuntimeError(error_msg)

            if not cli_response or not isinstance(cli_response, dict) or "result" not in cli_response:
                raise RuntimeError(f"Invalid CLI response format: {stdout_str}")

            result_content = cli_response["result"]
            if not result_content or not result_content.strip():
                raise RuntimeError(f"Empty response from Claude CLI. Full response: {cli_response}")

            response_data = self._extract_json(result_content)
            return response_schema.model_validate(response_data)

        except asyncio.TimeoutError:
            raise CriticalAPIError(f"Claude CLI timeout after {timeout} seconds - review cannot proceed")
        except CriticalAPIError:
            # Re-raise critical errors - these should NOT be gracefully degraded
            raise
        except json.JSONDecodeError as e:
            result_preview = cli_response.get("result", "")[:500] if cli_response else "N/A"
            error_msg = f"[CLAUDE-CLI-JSON-ERROR] Failed to parse Claude response as JSON: {e}\n"
            error_msg += f"Session ID: {session_id}\n"
            error_msg += f"Result preview: {result_preview}\n"
            if "unable to access" in result_preview.lower() or "mcp tools" in result_preview.lower():
                error_msg += f"\nMCP tools may not be configured correctly. Check Claude Code CLI setup.\n"
                error_msg += f"Allowed tools: {allowed_tools}"
            logger.error(error_msg)

            # Graceful degradation ONLY for JSON parsing issues with valid model response
            logger.warning(f"[GRACEFUL-DEGRADATION] Returning empty result for session {session_id}")
            return self._create_empty_response(response_schema, session_id)
        except Exception as e:
            # For unexpected errors, log and re-raise - don't silently approve
            logger.error(f"[CLAUDE-CLI-ERROR] Unexpected error in session {session_id}: {type(e).__name__}: {e}")
            raise CriticalAPIError(f"Unexpected error during Claude API call: {e}")

    @staticmethod
    def _check_for_critical_error(result_content: str, session_id: str) -> None:
        """Check if the result contains a critical API error that should not be gracefully degraded.

        Raises CriticalAPIError for:
        - Authentication errors (401)
        - Rate limiting (429)
        - Server errors (5xx)
        - Invalid API key errors
        """
        if not result_content:
            return

        result_lower = result_content.lower()

        # Check for authentication errors
        if "authentication_error" in result_lower or "401" in result_content:
            logger.error(f"[CRITICAL] Authentication error detected in session {session_id}")
            raise CriticalAPIError(f"Authentication failed - API key may be invalid or expired: {result_content[:200]}")

        # Check for rate limiting
        if "rate_limit" in result_lower or "429" in result_content:
            logger.error(f"[CRITICAL] Rate limit error detected in session {session_id}")
            raise CriticalAPIError(f"Rate limit exceeded: {result_content[:200]}")

        # Check for server errors (5xx)
        if re.search(r'\b5\d{2}\b', result_content) and "error" in result_lower:
            logger.error(f"[CRITICAL] Server error detected in session {session_id}")
            raise CriticalAPIError(f"Server error: {result_content[:200]}")

        # Check for invalid API key
        if "invalid" in result_lower and ("api" in result_lower or "key" in result_lower):
            logger.error(f"[CRITICAL] Invalid API key error detected in session {session_id}")
            raise CriticalAPIError(f"Invalid API key: {result_content[:200]}")

        # Check for general API errors that indicate systemic issues
        if "api error:" in result_lower:
            logger.error(f"[CRITICAL] API error detected in session {session_id}")
            raise CriticalAPIError(f"API error: {result_content[:200]}")

    @staticmethod
    def _build_prompt(system_message: str, user_message: str, response_schema: Type[BaseModel]) -> str:
        schema_json = response_schema.model_json_schema()
        return f"""{system_message}

{user_message}

WORKFLOW:
1. Analyze code (optionally use <thinking> tags)
2. Call add_pr_comment() for EACH violation
3. Output JSON summary (issues_posted = tool calls made)

RESPONSE STRUCTURE:
<thinking>
Your analysis here (optional)
</thinking>
{{"valid": "json"}}

CRITICAL: Your response MUST end with valid JSON. After </thinking> tag (if used), output ONLY JSON - no text, no markdown.

Schema: {json.dumps(schema_json, indent=2)}

Example with thinking:
<thinking>Reviewing... found 1 violation... calling add_pr_comment...</thinking>
{{"issues_posted": 1, "findings": [], "session_id": "abc"}}

Example without thinking:
{{"issues_posted": 0, "findings": [], "session_id": "abc"}}"""

    @staticmethod
    def _build_command(
            session_id: str,
            base_session_id: Optional[str],
            allowed_tools: Optional[List[str]],
            prompt: str,
            model: Optional[str] = None
    ) -> List[str]:
        """Build the Claude CLI command with appropriate flags."""
        cmd = ["claude", "--output-format", "json"]

        # Add model flag - prefer explicit override, fallback to config
        effective_model = model or config.ai.claude_code_model
        if effective_model:
            cmd.extend(["--model", effective_model])

        # Handle session management
        if base_session_id:
            # When forking, don't use --session-id (incompatible with --resume)
            cmd.extend(["--resume", base_session_id, "--fork-session"])
        else:
            # Only use --session-id when not resuming/forking
            cmd.extend(["--session-id", session_id])

        if allowed_tools:
            cmd.extend(["--allowed-tools", ",".join(allowed_tools)])

        cmd.extend(["-p", prompt])
        return cmd

    @staticmethod
    def _create_empty_response(response_schema: Type[BaseModel], session_id: str) -> BaseModel:
        """Create an empty/default response when JSON parsing fails."""
        # Create a minimal valid response based on common schema fields
        default_data = {
            "issues_posted": 0,
            "findings": [],
            "session_id": session_id
        }

        # Try to validate with the schema - if it fails, we'll get a clear error
        try:
            return response_schema.model_validate(default_data)
        except Exception as e:
            # If the schema doesn't match our defaults, try with just session_id
            logger.warning(f"Could not create default response with standard fields: {e}")
            try:
                return response_schema.model_validate({"session_id": session_id})
            except Exception as e2:
                # Last resort: create an instance with minimal data
                logger.error(f"Could not create empty response: {e2}")
                raise RuntimeError(f"Failed to create fallback response for schema {response_schema.__name__}")

    @staticmethod
    def _extract_json(result_str: str) -> dict:
        result_str = result_str.strip()

        # Filter out thinking tags - extract only content after </thinking>
        if "</thinking>" in result_str:
            thinking_end = result_str.rfind("</thinking>")
            result_str = result_str[thinking_end + len("</thinking>"):].strip()

        # Extract JSON by finding first { and last }
        first_brace = result_str.find("{")
        last_brace = result_str.rfind("}")

        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            result_str = result_str[first_brace:last_brace + 1]

        if result_str.startswith("{"):
            return json.loads(result_str)

        # Handle markdown code fences
        if "```json" in result_str:
            start = result_str.find("```json") + 7
            end = result_str.find("```", start)
        elif "```" in result_str:
            start = result_str.find("```") + 3
            end = result_str.find("```", start)
        else:
            return json.loads(result_str)

        if end != -1:
            result_str = result_str[start:end].strip()

        return json.loads(result_str)
