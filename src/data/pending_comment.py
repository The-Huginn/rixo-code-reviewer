from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4


@dataclass
class PendingComment:
    """A comment waiting to be published to Azure DevOps."""
    pr_url: str
    file_path: str
    line_start: int
    comment: str
    change_tracking_id: int
    agent_name: str
    session_id: str
    id: str = field(default_factory=lambda: str(uuid4()))

    # Duplicate tracking
    is_duplicate: bool = False
    duplicate_of: Optional[str] = None  # ID of the original comment if this is a duplicate

    # Iteration context for diff comparison
    iteration: Optional[int] = None  # PR iteration when comment was created

    # Pre-loaded vs new comment tracking
    is_existing: bool = False  # True if pre-loaded from Azure DevOps
    thread_id: Optional[int] = None  # Azure DevOps thread ID for existing comments

    # Processing state
    is_processed: bool = False  # True after duplicate check completed

    # Eager-loaded diff content
    diff: Optional[str] = None
