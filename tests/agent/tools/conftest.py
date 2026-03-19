"""Shared fixtures for agent tool tests."""

from unittest.mock import MagicMock

import pytest

from velo.agent.tools.cron import CronTool
from velo.cron.service import CronService


@pytest.fixture
def cron_tool():
    """Create a CronTool with mocked service and session context."""
    service = MagicMock(spec=CronService)
    mock_job = MagicMock()
    mock_job.name = "test"
    mock_job.id = "j123"
    service.add_job.return_value = mock_job
    tool = CronTool(service)
    tool.set_context("telegram", "12345")
    return tool
