import pytest
from unittest.mock import MagicMock
from src.client.azure.azure_devops_client import AzureDevOpsClient, PRDetails, FileChange


def test_azure_devops_client_initialization():
    """Test AzureDevOpsClient can be initialized"""
    mock_http_client = MagicMock()
    client = AzureDevOpsClient(http_client=mock_http_client)
    assert client is not None
    assert client.base_url is not None
    assert isinstance(client.base_url, str)


def test_azure_devops_client_uses_http_client():
    """Test AzureDevOpsClient stores the http client"""
    mock_http_client = MagicMock()
    client = AzureDevOpsClient(http_client=mock_http_client)
    assert client.http_client == mock_http_client


def test_pr_details_dataclass():
    """Test PRDetails dataclass"""
    details = PRDetails(
        pr_id=12345,
        title="Test PR",
        description="Test description",
        source_branch="feature/test",
        target_branch="main",
        author="test-user",
        repository="test-repo"
    )
    assert details.pr_id == 12345
    assert details.title == "Test PR"
    assert details.repository == "test-repo"


def test_file_change_dataclass():
    """Test FileChange dataclass"""
    change = FileChange(
        path="/src/main/Example.java",
        change_type="edit",
        change_tracking_id=42
    )
    assert change.path == "/src/main/Example.java"
    assert change.change_type == "edit"
    assert change.change_tracking_id == 42


