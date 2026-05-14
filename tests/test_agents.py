import pytest
from src.agent.impl import ArchitectureReviewAgent, StyleReviewAgent, TestReviewAgent
from src.data import (
    StyleReviewResult,
    ArchitectureReviewResult,
    TestReviewResult,
)


class MockAIClient:

    def __init__(self, findings=None):
        self.findings = findings or []
        self.last_system_message = None
        self.last_user_message = None

    async def structured_completion(self, system_message, user_message, response_schema, **kwargs):
        self.last_system_message = system_message
        self.last_user_message = user_message
        return response_schema(issues_posted=len(self.findings))

    def generate_session_id(self):
        return "mock-session-123"


class MockRuleLoaderService:

    def __init__(self):
        pass

    async def load_rules(self, rule_groups, framework="spring"):
        return f"Mock rules for groups: {', '.join(rule_groups)}"


@pytest.mark.asyncio
async def test_style_agent_review():
    ai_client = MockAIClient()
    rule_loader = MockRuleLoaderService()
    agent = StyleReviewAgent(ai_client, rule_loader)

    await agent.fetch_rules()
    result = await agent.review("Test.java", "diff...", "full file...", "", "", pr_url="http://example.com", change_tracking_id=1)

    assert isinstance(result, StyleReviewResult), "Should return StyleReviewResult"
    assert "style" in ai_client.last_system_message.lower(), \
        "System message should mention style"


@pytest.mark.asyncio
async def test_architecture_agent_review():
    ai_client = MockAIClient()
    rule_loader = MockRuleLoaderService()
    agent = ArchitectureReviewAgent(ai_client, rule_loader)

    await agent.fetch_rules()
    result = await agent.review_pr("http://example.com", [], [], [])

    assert isinstance(result, ArchitectureReviewResult), \
        "Should return ArchitectureReviewResult"
    assert "architecture" in ai_client.last_system_message.lower(), \
        "System message should mention architecture"


@pytest.mark.asyncio
async def test_test_agent_review():
    ai_client = MockAIClient()
    rule_loader = MockRuleLoaderService()
    agent = TestReviewAgent(ai_client, rule_loader)

    await agent.fetch_rules()
    result = await agent.review("TestClass.java", "diff...", "full file...", "", "", pr_url="http://example.com", change_tracking_id=1)

    assert isinstance(result, TestReviewResult), "Should return TestReviewResult"
    assert "test" in ai_client.last_system_message.lower(), \
        "System message should mention test"


@pytest.mark.asyncio
async def test_agent_includes_rules_in_system_message():
    ai_client = MockAIClient()
    rule_loader = MockRuleLoaderService()
    agent = StyleReviewAgent(ai_client, rule_loader)

    await agent.fetch_rules()
    await agent.review("Test.java", "diff...", "full file...", "", "", pr_url="http://example.com", change_tracking_id=1)

    assert "Mock rules for groups: style" in ai_client.last_system_message, \
        "System message should include rules loaded by agent"
