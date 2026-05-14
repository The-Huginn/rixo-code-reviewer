import pytest
from pydantic import ValidationError
from src.data.models import (
    Finding,
    StyleReviewResult,
    ArchitectureReviewResult,
    TestReviewResult,
    IntegrationReviewResult,
    AggregatedFindings
)


def test_finding_validation():
    """Test Finding model validation"""
    # Valid finding
    finding = Finding(
        file_path="src/main/java/Example.java",
        line_number=42,
        category="style",
        message_cs="Chyba v formatovani kodu."
    )
    assert finding.file_path == "src/main/java/Example.java"
    assert finding.line_number == 42
    assert finding.category == "style"

    # Invalid line number (< 1)
    with pytest.raises(ValidationError):
        Finding(
            file_path="test.java",
            line_number=0,
            category="style",
            message_cs="Test"
        )

    # Empty message
    with pytest.raises(ValidationError):
        Finding(
            file_path="test.java",
            line_number=1,
            category="style",
            message_cs=""
        )


def test_review_result_models():
    """Test review result models"""
    # Test review result types
    style_result = StyleReviewResult(issues_posted=1)
    assert style_result.issues_posted == 1

    arch_result = ArchitectureReviewResult(issues_posted=2)
    assert arch_result.issues_posted == 2

    test_result = TestReviewResult(issues_posted=3)
    assert test_result.issues_posted == 3

    integration_result = IntegrationReviewResult(issues_posted=0)
    assert integration_result.issues_posted == 0

    # Test default (no issues)
    empty_result = StyleReviewResult()
    assert empty_result.issues_posted == 0


def test_aggregated_findings_approval_logic():
    """Test AggregatedFindings approval vote logic"""
    issue = Finding(
        file_path="test.java",
        line_number=1,
        category="style",
        message_cs="Problem v kodu"
    )

    # Has issues -> wait-for-author
    agg = AggregatedFindings(issues=[issue])
    assert agg.has_issues is True
    assert agg.get_approval_vote() == "wait-for-author"

    # No issues -> approve
    agg = AggregatedFindings(issues=[])
    assert agg.has_issues is False
    assert agg.get_approval_vote() == "approve"
