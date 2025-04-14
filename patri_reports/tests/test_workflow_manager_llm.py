import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import os
import pytest

from patri_reports.workflow_manager import WorkflowManager
from patri_reports.models.case import CaseInfo


# Use pytest class for tests
class TestWorkflowManagerLLM:
    """Test the LLM integration in WorkflowManager."""

    def setup_method(self):
        """Set up test environment."""
        # Mock dependencies
        self.state_manager = MagicMock()
        self.case_manager = MagicMock()
        
        # Create a test case
        self.test_case = CaseInfo(
            case_id="TEST_CASE_123",
            case_number=123,
            case_year=2023,
            requesting_unit="Test Unit",
            address="123 Test St"
        )
        
        # Default to returning our test case from the case manager
        self.case_manager.load_case.return_value = self.test_case

    @patch.dict(os.environ, {"USE_ANTHROPIC": "false"})
    def test_init_with_openai_default(self):
        """Test that OpenAI is default when USE_ANTHROPIC is false."""
        workflow_manager = WorkflowManager(self.state_manager, self.case_manager)
        assert workflow_manager.use_anthropic is False

    @patch.dict(os.environ, {"USE_ANTHROPIC": "true", "ANTHROPIC_API_KEY": "test_key"})
    def test_init_with_anthropic_enabled(self):
        """Test that Anthropic is enabled when USE_ANTHROPIC is true and API key exists."""
        workflow_manager = WorkflowManager(self.state_manager, self.case_manager)
        assert workflow_manager.use_anthropic is True

    @patch.dict(os.environ, {"USE_ANTHROPIC": "true"})
    def test_fallback_without_anthropic_key(self):
        """Test fallback to OpenAI when Anthropic is enabled but no API key exists."""
        # Temporary unset any existing ANTHROPIC_API_KEY
        old_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            workflow_manager = WorkflowManager(self.state_manager, self.case_manager)
            assert workflow_manager.use_anthropic is False
        finally:
            # Restore the key if it existed
            if old_key:
                os.environ["ANTHROPIC_API_KEY"] = old_key

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"USE_ANTHROPIC": "false"})
    @patch('patri_reports.api.llm.LLMAPI.generate_summary')
    async def test_generate_llm_summary_with_openai(self, mock_generate_summary):
        """Test summary generation using OpenAI."""
        # Set up the mock
        mock_generate_summary.return_value = "Test summary from OpenAI"
        
        # Create WorkflowManager instance
        workflow_manager = WorkflowManager(self.state_manager, self.case_manager)
        
        # Set telegram_client to a mock
        workflow_manager.telegram_client = AsyncMock()
        
        # Set up send_message to return a mock message
        status_message = MagicMock()
        status_message.message_id = 12345
        workflow_manager.telegram_client.send_message.return_value = status_message
        
        # Run the test
        await workflow_manager.generate_llm_summary(123456, "TEST_CASE_123")
        
        # Verify the expected behavior
        mock_generate_summary.assert_called_once()
        self.case_manager.update_llm_data.assert_called_once_with("TEST_CASE_123", summary="Test summary from OpenAI")
        workflow_manager.telegram_client.send_message.assert_called()
        workflow_manager.telegram_client.edit_message_text.assert_called()
        
        # Check that the summary was sent to the user
        summary_sent = False
        for call in workflow_manager.telegram_client.send_message.call_args_list:
            args, kwargs = call
            if "*Case Summary*" in args[1]:
                assert "Test summary from OpenAI" in args[1]
                summary_sent = True
                break
        assert summary_sent, "Summary was not sent to the user"

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"USE_ANTHROPIC": "true", "ANTHROPIC_API_KEY": "test_key"})
    @patch('patri_reports.api.anthropic.AnthropicAPI.generate_summary')
    async def test_generate_llm_summary_with_anthropic(self, mock_generate_summary):
        """Test summary generation using Anthropic."""
        # Set up the mock
        mock_generate_summary.return_value = "Test summary from Claude"
        
        # Create WorkflowManager instance
        workflow_manager = WorkflowManager(self.state_manager, self.case_manager)
        
        # Set telegram_client to a mock
        workflow_manager.telegram_client = AsyncMock()
        
        # Set up send_message to return a mock message
        status_message = MagicMock()
        status_message.message_id = 12345
        workflow_manager.telegram_client.send_message.return_value = status_message
        
        # Run the test
        await workflow_manager.generate_llm_summary(123456, "TEST_CASE_123")
        
        # Verify the expected behavior
        mock_generate_summary.assert_called_once()
        self.case_manager.update_llm_data.assert_called_once_with("TEST_CASE_123", summary="Test summary from Claude")
        workflow_manager.telegram_client.send_message.assert_called()
        workflow_manager.telegram_client.edit_message_text.assert_called()
        
        # Check that the summary was sent to the user
        summary_sent = False
        for call in workflow_manager.telegram_client.send_message.call_args_list:
            args, kwargs = call
            if "*Case Summary*" in args[1]:
                assert "Test summary from Claude" in args[1]
                summary_sent = True
                break
        assert summary_sent, "Summary was not sent to the user"

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"USE_ANTHROPIC": "true", "ANTHROPIC_API_KEY": "test_key"})
    @patch('patri_reports.api.anthropic.AnthropicAPI.generate_summary')
    @patch('patri_reports.api.llm.LLMAPI.generate_summary')
    async def test_fallback_to_openai_on_anthropic_error(self, mock_openai_summary, mock_anthropic_summary):
        """Test fallback to OpenAI when Anthropic has an error."""
        # Set up the mocks - Anthropic will raise an exception, OpenAI will succeed
        mock_anthropic_summary.side_effect = Exception("Anthropic API error")
        mock_openai_summary.return_value = "Fallback summary from OpenAI"
        
        # Create WorkflowManager instance
        workflow_manager = WorkflowManager(self.state_manager, self.case_manager)
        
        # The key issue: we need to set the OpenAI API key to enable fallback
        workflow_manager.llm_api.api_key = "test_openai_key"
        
        # Set telegram_client to a mock
        workflow_manager.telegram_client = AsyncMock()
        
        # Set up send_message to return a mock message
        status_message = MagicMock()
        status_message.message_id = 12345
        workflow_manager.telegram_client.send_message.return_value = status_message
        
        # Run the test
        await workflow_manager.generate_llm_summary(123456, "TEST_CASE_123")
        
        # Verify the expected behavior
        mock_anthropic_summary.assert_called_once()
        mock_openai_summary.assert_called_once()
        self.case_manager.update_llm_data.assert_called_once_with("TEST_CASE_123", summary="Fallback summary from OpenAI")
        
        # Check that the fallback summary was sent to the user
        summary_sent = False
        for call in workflow_manager.telegram_client.send_message.call_args_list:
            args, kwargs = call
            if "*Case Summary*" in args[1]:
                assert "Fallback summary from OpenAI" in args[1]
                summary_sent = True
                break
        assert summary_sent, "Fallback summary was not sent to the user" 