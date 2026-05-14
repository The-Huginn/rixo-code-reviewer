import pytest
from unittest.mock import MagicMock
from src.service.pr_review_service import PRReviewService
from src.client.azure.azure_devops_client import PRDetails


class TestShouldSkipReview:
    """Test _should_skip_review method"""

    @pytest.fixture
    def service(self):
        mock_client = MagicMock()
        return PRReviewService(devops_client=mock_client, per_file_agents=[])

    def _make_pr_details(self, source: str, target: str, author: str = "user", repository: str = "rixo-service-b") -> PRDetails:
        return PRDetails(
            pr_id=1,
            title="Test",
            description="",
            source_branch=source,
            target_branch=target,
            author=author,
            repository=repository
        )

    def test_skip_release_tool_author(self, service):
        pr = self._make_pr_details(
            "refs/heads/task/DOK-123",
            "refs/heads/feature/DOK-100",
            author="rixo-ignored-author"
        )
        assert service._should_skip_review(pr) is True

    def test_skip_feature_to_develop(self, service):
        pr = self._make_pr_details("refs/heads/feature/DOK-123", "refs/heads/develop")
        assert service._should_skip_review(pr) is True

    def test_skip_release_to_develop(self, service):
        pr = self._make_pr_details("refs/heads/release/1.0.0", "refs/heads/develop")
        assert service._should_skip_review(pr) is True

    def test_skip_hotfix_to_develop(self, service):
        pr = self._make_pr_details("refs/heads/hotfix/fix-bug", "refs/heads/develop")
        assert service._should_skip_review(pr) is True

    def test_skip_release_to_master(self, service):
        pr = self._make_pr_details("refs/heads/release/1.0.0", "refs/heads/master")
        assert service._should_skip_review(pr) is True

    def test_skip_hotfix_to_master(self, service):
        pr = self._make_pr_details("refs/heads/hotfix/fix-bug", "refs/heads/master")
        assert service._should_skip_review(pr) is True

    def test_no_skip_feature_to_master(self, service):
        pr = self._make_pr_details("refs/heads/feature/DOK-123", "refs/heads/master")
        assert service._should_skip_review(pr) is False

    def test_no_skip_task_to_feature(self, service):
        pr = self._make_pr_details("refs/heads/task/DOK-456", "refs/heads/feature/DOK-123")
        assert service._should_skip_review(pr) is False

    def test_no_skip_task_to_develop(self, service):
        pr = self._make_pr_details("refs/heads/task/DOK-456", "refs/heads/develop")
        assert service._should_skip_review(pr) is False

    def test_no_skip_task_to_master(self, service):
        pr = self._make_pr_details("refs/heads/task/DOK-456", "refs/heads/master")
        assert service._should_skip_review(pr) is False

    def test_skip_repository_not_in_whitelist(self, service):
        pr = self._make_pr_details(
            "refs/heads/task/DOK-456",
            "refs/heads/feature/DOK-123",
            repository="unknown-repo"
        )
        assert service._should_skip_review(pr) is True

    def test_no_skip_whitelisted_repository(self, service):
        pr = self._make_pr_details(
            "refs/heads/task/DOK-456",
            "refs/heads/feature/DOK-123",
            repository="rixo-service-b"
        )
        assert service._should_skip_review(pr) is False

    def test_skip_rixo_ai_not_whitelisted(self, service):
        pr = self._make_pr_details(
            "refs/heads/task/DOK-456",
            "refs/heads/feature/DOK-123",
            repository="rixo-ai-service-service"
        )
        assert service._should_skip_review(pr) is True

    def test_skip_rixo_code_reviewer_not_whitelisted(self, service):
        pr = self._make_pr_details(
            "refs/heads/task/DOK-456",
            "refs/heads/feature/DOK-123",
            repository="rixo-code-reviewer"
        )
        assert service._should_skip_review(pr) is True

    def test_no_skip_empty_repository(self, service):
        """Empty repository should not trigger skip (backwards compatibility)"""
        pr = self._make_pr_details(
            "refs/heads/task/DOK-456",
            "refs/heads/feature/DOK-123",
            repository=""
        )
        assert service._should_skip_review(pr) is False
