import json
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from src.client.ai.claude_code_client import ClaudeCodeClient, CriticalAPIError
from src.data.models import StyleReviewResult


@pytest.fixture
def client():
    return ClaudeCodeClient()


@pytest.mark.asyncio
async def test_structured_completion_success(client):
    """Test successful structured completion"""
    mock_response = {
        "result": json.dumps({
            "issues_posted": 1,
            "session_id": "test-session-123"
        })
    }

    with patch('asyncio.create_subprocess_exec') as mock_exec:
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (
            json.dumps(mock_response).encode(),
            b""
        )
        mock_exec.return_value = mock_process

        result = await client.structured_completion(
            system_message="You are a reviewer",
            user_message="Review this code",
            response_schema=StyleReviewResult
        )

        assert isinstance(result, StyleReviewResult)
        assert result.issues_posted == 1

        mock_exec.assert_called_once()
        call_args = mock_exec.call_args[0]
        assert call_args[0] == "claude"
        assert "--output-format" in call_args
        assert "json" in call_args


@pytest.mark.asyncio
async def test_structured_completion_timeout(client):
    """Test timeout handling raises CriticalAPIError"""
    with patch('asyncio.create_subprocess_exec') as mock_exec:
        mock_process = AsyncMock()
        mock_process.communicate.side_effect = asyncio.TimeoutError()
        mock_exec.return_value = mock_process

        with pytest.raises(CriticalAPIError, match="timeout"):
            await client.structured_completion(
                system_message="Test",
                user_message="Test",
                response_schema=StyleReviewResult
            )


@pytest.mark.asyncio
async def test_structured_completion_cli_error(client):
    """Test Claude CLI error handling raises CriticalAPIError"""
    with patch('asyncio.create_subprocess_exec') as mock_exec:
        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate.return_value = (b"", b"Claude CLI error")
        mock_exec.return_value = mock_process

        # CLI errors now raise CriticalAPIError instead of graceful degradation
        with pytest.raises(CriticalAPIError):
            await client.structured_completion(
                system_message="Test",
                user_message="Test",
                response_schema=StyleReviewResult
            )


@pytest.mark.asyncio
async def test_structured_completion_graceful_degradation(client):
    """Test graceful degradation on invalid JSON"""
    mock_response = {
        "result": "Not valid JSON at all"
    }

    with patch('asyncio.create_subprocess_exec') as mock_exec:
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (
            json.dumps(mock_response).encode(),
            b""
        )
        mock_exec.return_value = mock_process

        # Should return empty result instead of raising
        result = await client.structured_completion(
            system_message="Test",
            user_message="Test",
            response_schema=StyleReviewResult
        )

        assert isinstance(result, StyleReviewResult)
        assert result.issues_posted == 0


def test_generate_session_id(client):
    """Test session ID generation"""
    session_id = client.generate_session_id()
    assert isinstance(session_id, str)
    assert len(session_id) == 36  # UUID format


def test_extract_json_simple():
    """Test JSON extraction from simple response"""
    result = ClaudeCodeClient._extract_json('{"issues_posted": 1}')
    assert result == {"issues_posted": 1}


def test_extract_json_with_thinking():
    """Test JSON extraction with thinking tags"""
    response = """<thinking>
    Analyzing the code...
    Found 1 issue.
    </thinking>
    {"issues_posted": 1}"""
    result = ClaudeCodeClient._extract_json(response)
    assert result == {"issues_posted": 1}


def test_extract_json_with_markdown():
    """Test JSON extraction from markdown code block"""
    response = """```json
    {"issues_posted": 2}
    ```"""
    result = ClaudeCodeClient._extract_json(response)
    assert result == {"issues_posted": 2}


@pytest.mark.asyncio
async def test_structured_completion_auth_error(client):
    """Test authentication error raises CriticalAPIError (not graceful degradation)"""
    # Simulates the error from the user's logs: {"is_error":true,"result":"API Error: 401...authentication_error"}
    mock_response = {
        "type": "result",
        "subtype": "success",
        "is_error": True,
        "result": 'API Error: 401 {"type":"error","error":{"type":"authentication_error","message":"OAuth token expired"}}'
    }

    with patch('asyncio.create_subprocess_exec') as mock_exec:
        mock_process = AsyncMock()
        mock_process.returncode = 0  # CLI itself succeeds but response has is_error=True
        mock_process.communicate.return_value = (
            json.dumps(mock_response).encode(),
            b""
        )
        mock_exec.return_value = mock_process

        # Should raise CriticalAPIError for auth failures, NOT return empty result
        with pytest.raises(CriticalAPIError, match="Authentication"):
            await client.structured_completion(
                system_message="Test",
                user_message="Test",
                response_schema=StyleReviewResult
            )


def test_check_for_critical_error_auth():
    """Test _check_for_critical_error detects authentication errors"""
    with pytest.raises(CriticalAPIError, match="Authentication"):
        ClaudeCodeClient._check_for_critical_error(
            'API Error: 401 {"type":"error","error":{"type":"authentication_error"}}',
            "test-session"
        )


def test_check_for_critical_error_rate_limit():
    """Test _check_for_critical_error detects rate limiting"""
    with pytest.raises(CriticalAPIError, match="Rate limit"):
        ClaudeCodeClient._check_for_critical_error(
            'API Error: 429 rate_limit_exceeded',
            "test-session"
        )


def test_check_for_critical_error_no_error():
    """Test _check_for_critical_error passes on valid response"""
    # Should not raise
    ClaudeCodeClient._check_for_critical_error(
        '{"issues_posted": 0}',
        "test-session"
    )
