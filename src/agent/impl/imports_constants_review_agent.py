import re
from typing import Type, List, TYPE_CHECKING, override, Optional

from src.agent import SingleFileAgent
from src.client.azure import AzureDevOpsClient
from src.data import ImportsConstantsReviewResult
from src.client.ai import AIClient
from src.service.pending_comments_pool import PendingCommentsPool

if TYPE_CHECKING:
    from src.service import RuleLoaderService

# Prefix to clarify the diff content
CODE_ONLY_NOTICE = """NOTE: Import statements have been stripped from this diff. Focus on constants usage in the code.
"""


class ImportsConstantsReviewAgent(SingleFileAgent[ImportsConstantsReviewResult]):

    def __init__(self, ai_client: AIClient, rule_loader: "RuleLoaderService"):
        super().__init__(ai_client, rule_loader)

    @override
    def _get_file_pattern(self) -> Optional[str]:
        return r"\.(java|kt)$"

    @override
    def should_review_file(self, file_path: str) -> bool:
        if not super().should_review_file(file_path):
            return False

        # Exclude test files
        test_patterns = [
            r"Test\.java$",
            r"Test\.kt$",
            r"/test/",
            r"/tests/",
            r"Tests\.java$",
            r"Tests\.kt$",
        ]
        for pattern in test_patterns:
            if re.search(pattern, file_path):
                return False

        return True

    def _get_rule_groups(self) -> List[str]:
        return ["imports-constants"]

    def _get_specialty(self) -> str:
        return "import statements and constants usage"

    def _get_response_schema(self) -> Type[ImportsConstantsReviewResult]:
        return ImportsConstantsReviewResult

    def _get_agent_name(self) -> str:
        return "ImportsConstantsReviewAgent"

    @override
    async def review(
            self,
            file_path: str,
            diff: str,
            pr_url: str,
            change_tracking_id: int,
            devops_client: AzureDevOpsClient,
            all_files: list[str] = None,
            pending_pool: Optional[PendingCommentsPool] = None,
            current_iteration: Optional[int] = None
    ) -> ImportsConstantsReviewResult:
        # Remove import lines from diff
        sanitized_diff = self._remove_imports_from_diff(diff)

        # Add context notice
        sanitized_diff = f"{CODE_ONLY_NOTICE}\n{sanitized_diff}"

        return await super().review(
            file_path, sanitized_diff, pr_url, change_tracking_id,
            devops_client, all_files, pending_pool, current_iteration
        )

    def _remove_imports_from_diff(self, diff: str) -> str:
        """Remove import/package statement lines from the diff."""
        lines = diff.split('\n')
        filtered_lines = []

        for line in lines:
            # Always keep structural lines
            if line.startswith('--- ') or line.startswith('+++ '):
                filtered_lines.append(line)
                continue
            if line.startswith('--- DIFF') or line.startswith('--- END'):
                filtered_lines.append(line)
                continue
            if line.startswith('@@'):
                filtered_lines.append(line)
                continue

            # Skip import and package lines
            # Diff format patterns:
            # - Unchanged: "   1,   1  import ..." (2 spaces before content)
            # - Added:     "   7+ import ..." (+ then space before content)
            # - Removed:   "  15- import ..." (- then space before content)
            if ('  package ' in line or '  import ' in line or
                '+ package ' in line or '+ import ' in line or
                '- package ' in line or '- import ' in line):
                continue

            filtered_lines.append(line)

        return '\n'.join(filtered_lines)
