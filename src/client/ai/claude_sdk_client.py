import json
import logging
import re
from typing import Type, Optional, List, Dict
from uuid import uuid4

from claude_code_sdk import query, ClaudeCodeOptions, ResultMessage, SystemMessage
from claude_code_sdk.client import ClaudeSDKClient as SDKBidirectionalClient
from claude_code_sdk.types import HookEvent, HookMatcher
from pydantic import BaseModel
from src.config import config
from src.client.ai.claude_code_client import CriticalAPIError, ClaudeCodeClient

logger = logging.getLogger(__name__)


class ClaudeSDKClient:
    """Client for interacting with Claude Code SDK."""

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
            model: Optional[str] = None,
            hooks: Optional[Dict[HookEvent, List[HookMatcher]]] = None
    ) -> BaseModel:
        if session_id is None:
            session_id = self.generate_session_id()

        prompt = self._build_prompt(user_message, response_schema)
        options = self._build_options(
            session_id, base_session_id, allowed_tools, system_message,
            model, hooks
        )

        # Log details for debugging
        logger.debug(f"Executing Claude SDK query with prompt length: {len(prompt)} chars")
        if base_session_id:
            logger.debug(f"Forking from base session: {base_session_id}")
        logger.debug(f"Session ID: {session_id}, Allowed tools: {allowed_tools}, Hooks: {hooks is not None}")

        try:
            result_text = None
            actual_session_id = None
            tool_calls_made = []

            # Use bidirectional client when hooks are provided (required for hooks to work)
            # The query() function doesn't support hooks properly - need ClaudeSDKClient
            if hooks:
                logger.info(f"[SDK] Using bidirectional client for hooks")
                result_text, actual_session_id, tool_calls_made = await self._query_with_hooks(
                    prompt, options
                )
            else:
                # Use simple query() for efficiency when no hooks
                async for message in query(prompt=prompt, options=options):
                    if isinstance(message, SystemMessage):
                        actual_session_id = message.data.get("session_id")

                    if hasattr(message, 'content'):
                        for block in message.content:
                            if hasattr(block, 'name'):
                                tool_calls_made.append(block.name)
                                logger.debug(f"[SDK-TOOL] Tool called: {block.name}")

                    if isinstance(message, ResultMessage):
                        if message.is_error:
                            error_msg = f"Claude SDK returned error: {message.result}"
                            logger.error(error_msg)
                            self._check_for_critical_error(message.result, session_id)
                            raise RuntimeError(error_msg)
                        result_text = message.result
                        logger.debug(f"Received result from SDK, length: {len(result_text)} chars")

            # Log tool usage summary
            if tool_calls_made:
                logger.info(f"[SDK-TOOLS] Session {actual_session_id or session_id}: {len(tool_calls_made)} tool calls: {', '.join(set(tool_calls_made))}")

            if not result_text or not result_text.strip():
                raise RuntimeError("Empty response from Claude SDK")

            # Log response for debugging (first 500 chars)
            logger.info(f"[SDK] Response preview (first 500 chars): {result_text[:500]}")

            response_data = self._extract_json(result_text)
            return response_schema.model_validate(response_data)

        except CriticalAPIError:
            # Re-raise critical errors - these should NOT be gracefully degraded
            raise
        except json.JSONDecodeError as e:
            # JSON parsing failed - log and return default response
            result_preview = result_text[:500] if result_text else "N/A"
            logger.warning(f"[SDK] Failed to parse response as JSON: {e}. Preview: {result_preview}")
            if "unable to access" in result_preview.lower() or "mcp tools" in result_preview.lower():
                logger.warning(f"[SDK] MCP tools may not be configured correctly. Allowed tools: {allowed_tools}")
            # Return default empty response instead of raising
            return response_schema.model_validate({})
        except Exception as e:
            error_msg = f"Claude SDK error: {str(e)}"
            logger.error(error_msg)
            raise CriticalAPIError(f"Unexpected error during Claude SDK call: {e}")

    async def _query_with_hooks(
            self,
            prompt: str,
            options: ClaudeCodeOptions
    ) -> tuple[str, str, list]:
        """Execute query using bidirectional client for hook support.

        The query() function doesn't properly support hooks because it closes
        the stream before hook callbacks can be processed. The bidirectional
        ClaudeSDKClient keeps the connection open for hook callbacks.

        Returns:
            tuple of (result_text, session_id, tool_calls_made)
        """
        result_text = None
        actual_session_id = None
        tool_calls_made = []

        client = SDKBidirectionalClient(options)

        try:
            # Connect without initial prompt (keeps stream open for hooks)
            await client.connect()
            logger.debug("[SDK] Bidirectional client connected")

            # Send the query
            await client.query(prompt)

            # Receive response
            async for message in client.receive_response():
                if isinstance(message, SystemMessage):
                    actual_session_id = message.data.get("session_id")

                if hasattr(message, 'content'):
                    for block in message.content:
                        if hasattr(block, 'name'):
                            tool_calls_made.append(block.name)
                            logger.debug(f"[SDK-TOOL] Tool called: {block.name}")

                if isinstance(message, ResultMessage):
                    if message.is_error:
                        error_msg = f"Claude SDK returned error: {message.result}"
                        logger.error(error_msg)
                        self._check_for_critical_error(message.result, actual_session_id or "unknown")
                        raise RuntimeError(error_msg)
                    result_text = message.result
                    actual_session_id = actual_session_id or message.session_id
                    logger.debug(f"Received result from SDK, length: {len(result_text) if result_text else 0} chars")

        finally:
            await client.disconnect()
            logger.debug("[SDK] Bidirectional client disconnected")

        return result_text, actual_session_id, tool_calls_made

    @staticmethod
    def _check_for_critical_error(result_content: str, session_id: str) -> None:
        """Check if the result contains a critical API error.

        Delegates to ClaudeCodeClient's implementation for consistency.
        """
        ClaudeCodeClient._check_for_critical_error(result_content, session_id)

    @staticmethod
    def _build_prompt(user_message: str, response_schema: Type[BaseModel]) -> str:
        """Build the prompt with JSON schema and response structure.

        Matches CLI client approach - embeds schema and examples in prompt.
        """
        schema_json = response_schema.model_json_schema()
        return f"""{user_message}

RESPONSE STRUCTURE:
{{"valid": "json"}}

CRITICAL REQUIREMENTS:
1. Your response MUST be valid JSON only - no text before or after
2. Do NOT use <thinking> tags - output JSON directly
3. No markdown code blocks - raw JSON only

Schema: {json.dumps(schema_json, indent=2)}"""

    @staticmethod
    def _build_options(
            session_id: str,
            base_session_id: Optional[str],
            allowed_tools: Optional[List[str]],
            system_message: str,
            model: Optional[str] = None,
            hooks: Optional[Dict[HookEvent, List[HookMatcher]]] = None
    ) -> ClaudeCodeOptions:
        """Build the Claude SDK options with appropriate configuration."""
        options = ClaudeCodeOptions()

        options.system_prompt = system_message

        effective_model = model or config.ai.claude_code_model
        if effective_model:
            options.model = effective_model

        if base_session_id:
            options.resume = base_session_id
        else:
            options.session_id = session_id

        if allowed_tools:
            options.allowed_tools = allowed_tools

        if hooks:
            options.hooks = hooks

        # Note: Claude Code SDK does not support structured output enforcement.
        # JSON output is enforced via system/user prompts in each agent.

        return options

    @staticmethod
    def _extract_json(result_str: str) -> dict:
        result_str = result_str.strip()

        # Handle thinking blocks - remove them entirely
        if "</thinking>" in result_str:
            thinking_end = result_str.rfind("</thinking>")
            result_str = result_str[thinking_end + len("</thinking>"):].strip()
        elif "<thinking>" in result_str:
            # Truncated thinking block without closing tag - response was cut off
            # This means no JSON was produced
            raise json.JSONDecodeError(
                "Response contains only thinking block without JSON output (likely truncated)",
                result_str[:100],
                0
            )

        # Check if we have any content left after removing thinking
        if not result_str:
            raise json.JSONDecodeError(
                "Response contains only thinking block without JSON output",
                "empty after thinking removal",
                0
            )

        first_brace = result_str.find("{")
        last_brace = result_str.rfind("}")

        if first_brace == -1 or last_brace == -1 or last_brace <= first_brace:
            raise json.JSONDecodeError(
                f"No valid JSON object found in response",
                result_str[:100] if result_str else "empty",
                0
            )

        result_str = result_str[first_brace:last_brace + 1]

        return json.loads(result_str)
