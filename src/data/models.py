from dataclasses import dataclass
from typing import List, Literal

from pydantic import BaseModel, Field

from src.constants import VOTE_APPROVE, VOTE_WAIT_FOR_AUTHOR


class Finding(BaseModel):
    file_path: str = Field(..., description="File path relative to repository root")
    line_number: int = Field(..., ge=1, description="Line number in file")
    category: str = Field(..., description="Finding category (style, architecture, test, logic)")
    message_cs: str = Field(..., min_length=1, description="Czech message, max 2 sentences")
    agent_name: str = Field(default="", description="Name of agent that found this issue")
    session_id: str = Field(default="", description="Claude session ID for debugging")


class ReviewSummary(BaseModel):
    issues_posted: int = Field(default=0, description="Number of issues posted")
    session_id: str = Field(default="", description="Claude session ID for debugging")


class StyleReviewResult(ReviewSummary):
    pass


class ArchitectureReviewResult(ReviewSummary):
    pass


class TestReviewResult(ReviewSummary):
    pass


class IntegrationReviewResult(ReviewSummary):
    pass


class FileIntegrityReviewResult(ReviewSummary):
    pass


class SQLReviewResult(ReviewSummary):
    pass


class DocumentationReviewResult(ReviewSummary):
    pass


class SecurityReviewResult(ReviewSummary):
    pass


class ImportsConstantsReviewResult(ReviewSummary):
    pass


class SingleThreadResult(BaseModel):
    """Result of processing a single thread"""
    thread_id: int = Field(..., description="Thread ID that was processed")
    resolved: bool = Field(default=False, description="Whether the thread was resolved")
    session_id: str = Field(default="", description="Claude session ID for debugging")


class ThreadManagerResult(BaseModel):
    verdict: Literal["approve", "wait-for-author", "reject"] = Field(
        ...,
        description="Final verdict based on unresolved threads"
    )
    threads_processed: int = Field(default=0, description="Total number of threads processed")
    threads_resolved: int = Field(default=0, description="Number of threads resolved")
    unresolved_issues: int = Field(default=0, description="Number of unresolved issue threads")
    session_id: str = Field(default="", description="Claude session ID for debugging")


@dataclass
class AggregatedFindings:
    issues: List[Finding]

    @property
    def has_issues(self) -> bool:
        return len(self.issues) > 0

    def get_approval_vote(self) -> str:
        if self.has_issues:
            return VOTE_WAIT_FOR_AUTHOR
        else:
            return VOTE_APPROVE


@dataclass
class PublishResult:
    success_count: int
    failure_count: int

    @property
    def total(self) -> int:
        return self.success_count + self.failure_count


