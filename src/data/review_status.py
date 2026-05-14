from datetime import datetime
from typing import Optional, Dict
from enum import Enum
from dataclasses import dataclass, asdict


class ReviewStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ReviewResult:
    issues: int
    vote: str


@dataclass
class ReviewState:
    pr_url: str
    status: ReviewStatus
    result: Optional[ReviewResult] = None
    session_id: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        data = asdict(self)
        data['status'] = self.status.value
        if self.started_at:
            data['started_at'] = self.started_at.isoformat()
        if self.completed_at:
            data['completed_at'] = self.completed_at.isoformat()
        return data
