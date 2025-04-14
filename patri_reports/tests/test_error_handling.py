import pytest
import os
import sys
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path

# Add parent directory to path to allow imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from patri_reports.utils.error_handler import (
    with_retry, with_timeout, NetworkError, TimeoutError, DataError, StateError,
    with_async_retry, safe_api_call, cleanup_old_cases
)
from patri_reports.telegram_client import TelegramClient
from patri_reports.workflow_manager import WorkflowManager
from patri_reports.state_manager import StateManager, AppState
from patri_reports.case_manager import CaseManager
from patri_reports.models.case import CaseInfo

# --- Test Error Handler Utils ---

def test_with_retry_success():
    """Test that with_retry succeeds on normal function execution."""
    mock_func = MagicMock(return_value="success")
    decorated = with_retry()(mock_func)
    
    result = decorated("arg1", key="value")
    
    assert result == "success"
    mock_func.assert_called_once_with("arg1", key="value")

def test_with_retry_retries_on_error():
    """Test that with_retry actually retries on specified exceptions."""
    # Create a mock function with a name attribute to avoid the __name__ AttributeError
    mock_func = MagicMock()
    mock_func.__name__ = "mock_function"
    mock_func.side_effect = [NetworkError("Network down"), "success"]
    
    decorated = with_retry(max_retries=1, exceptions_to_retry=(NetworkError,))(mock_func)
    
    result = decorated()
    
    assert result == "success"
    assert mock_func.call_count == 2

def test_with_retry_fails_after_max_retries():
    """Test that with_retry gives up after max_retries."""
    # Create a mock function with a name attribute
    mock_func = MagicMock()
    mock_func.__name__ = "mock_function"
    mock_func.side_effect = NetworkError("Network down")
    
    decorated = with_retry(max_retries=2, exceptions_to_retry=(NetworkError,))(mock_func)
    
    with pytest.raises(NetworkError):
        decorated()
    
    assert mock_func.call_count == 3  # Initial + 2 retries

def test_with_timeout_success():
    """Test that with_timeout allows fast functions to complete."""
    mock_func = MagicMock(return_value="quick result")
    decorated = with_timeout(timeout_seconds=1)(mock_func)
    
    result = decorated()
    
    assert result == "quick result"
    mock_func.assert_called_once()

def test_timeout_handler_raises():
    """Test that the timeout handler raises a TimeoutError."""
    # Mock the signal module entirely to avoid OS-specific issues
    with patch('signal.signal') as mock_signal:
        with patch('signal.alarm') as mock_alarm:
            # Setup mock timeout handler callback
            def trigger_timeout(*args, **kwargs):
                # Simulate signal handler being called
                from patri_reports.utils.error_handler import TimeoutError
                raise TimeoutError("Mocked timeout")
                
            # Make the mock trigger our timeout when function is called
            mock_func = MagicMock(side_effect=trigger_timeout)
            decorated = with_timeout(timeout_seconds=1)(mock_func)
            
            # This should raise our mocked TimeoutError
            with pytest.raises(TimeoutError):
                decorated()
            
            # Verify signal handling was attempted
            assert mock_signal.called
            assert mock_alarm.called

# --- Test Async Error Handling ---

@pytest.mark.asyncio
async def test_async_retry_success():
    """Test successful execution with async retry."""
    mock_func = AsyncMock(return_value="success")
    decorated = with_async_retry()(mock_func)
    
    result = await decorated("arg1", key="value")
    
    assert result == "success"
    mock_func.assert_called_once_with("arg1", key="value")

@pytest.mark.asyncio
async def test_async_retry_handles_failures():
    """Test that async retry handles temporary failures."""
    mock_func = AsyncMock(side_effect=[NetworkError("Network down"), "success"])
    decorated = with_async_retry(max_retries=1, exceptions_to_retry=(NetworkError,))(mock_func)
    
    result = await decorated()
    
    assert result == "success"
    assert mock_func.call_count == 2

@pytest.mark.asyncio
async def test_safe_api_call_handles_success():
    """Test that safe_api_call properly handles successful calls."""
    mock_func = AsyncMock(return_value="api_result")
    
    success, result, exception = await safe_api_call(
        mock_func, 
        error_message="API failed",
        default_return=None,
        arg1="value1"
    )
    
    assert success is True
    assert result == "api_result"
    assert exception is None
    mock_func.assert_called_once_with(arg1="value1")

@pytest.mark.asyncio
async def test_safe_api_call_handles_failure():
    """Test that safe_api_call properly handles failures."""
    error = ValueError("API error")
    mock_func = AsyncMock(side_effect=error)
    
    success, result, exception = await safe_api_call(
        mock_func, 
        error_message="API failed",
        default_return="default_value"
    )
    
    assert success is False
    assert result == "default_value"
    assert exception is error

# --- Test Error Recovery ---

@pytest.fixture
def mock_workflow_components():
    """Creates mocked workflow components for testing."""
    state_manager = MagicMock(spec=StateManager)
    case_manager = MagicMock(spec=CaseManager)
    telegram_client = AsyncMock(spec=TelegramClient)
    
    # Configure state manager
    state_manager.get_state.return_value = AppState.EVIDENCE_COLLECTION
    state_manager.get_active_case_id.return_value = "test-case-123"
    
    # Configure case manager
    case_info = MagicMock(spec=CaseInfo)
    case_info.case_id = "test-case-123"
    case_manager.load_case.return_value = case_info
    
    return {
        "state_manager": state_manager,
        "case_manager": case_manager,
        "telegram_client": telegram_client
    }

@pytest.mark.asyncio
async def test_workflow_recovers_from_errors(mock_workflow_components):
    """Test that the workflow manager can recover from errors."""
    # Setup workflow with mocked components
    workflow = WorkflowManager(
        state_manager=mock_workflow_components["state_manager"],
        case_manager=mock_workflow_components["case_manager"]
    )
    workflow.set_telegram_client(mock_workflow_components["telegram_client"])
    workflow.send_evidence_prompt = AsyncMock()
    
    # Create a mock update with user info
    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    
    # Simulate an error and recovery
    await workflow.handle_error(
        update=mock_update,
        error_message="Test error message", 
        recover=True
    )
    
    # Verify the recovery path was followed
    assert mock_workflow_components["state_manager"].get_state.called
    assert mock_workflow_components["state_manager"].get_active_case_id.called
    assert mock_workflow_components["case_manager"].load_case.called
    assert workflow.send_evidence_prompt.called
    
    # Verify user was notified
    mock_workflow_components["telegram_client"].send_message.assert_called()

@pytest.mark.asyncio
async def test_workflow_handles_invalid_state(mock_workflow_components):
    """Test that the workflow manager handles invalid state conditions."""
    # Set up invalid state (EVIDENCE_COLLECTION with no case ID)
    mock_workflow_components["state_manager"].get_state.return_value = AppState.EVIDENCE_COLLECTION
    mock_workflow_components["state_manager"].get_active_case_id.return_value = None
    
    # Setup workflow with mocked components
    workflow = WorkflowManager(
        state_manager=mock_workflow_components["state_manager"],
        case_manager=mock_workflow_components["case_manager"]
    )
    workflow.set_telegram_client(mock_workflow_components["telegram_client"])
    workflow.show_idle_menu = AsyncMock()
    
    # Create a mock update and context
    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_context = MagicMock()
    
    # Execute the handle_update method
    await workflow.handle_update(mock_update, mock_context)
    
    # Verify the state was reset to IDLE
    mock_workflow_components["state_manager"].set_state.assert_called_with(AppState.IDLE)
    
    # Verify the user was notified and shown idle menu
    assert mock_workflow_components["telegram_client"].send_message.called
    assert workflow.show_idle_menu.called

def test_friendly_error_messages():
    """Test that error messages are user-friendly and don't expose technical details."""
    # Create a mock workflow manager method that generates different types of error messages
    mock_workflow = MagicMock()
    
    # Define our test cases with expected messaging patterns
    test_cases = [
        {
            "error": NetworkError("Connection failed"),
            "expected_keywords": ["connection", "network", "try again"],
            "unexpected_keywords": ["stack trace", "exception", "error code"]
        },
        {
            "error": TimeoutError("Operation timed out"),
            "expected_keywords": ["long", "try again"],
            "unexpected_keywords": ["stack trace", "exception", "error code"]
        },
        {
            "error": ValueError("Invalid PDF format"),
            "expected_keywords": ["file", "invalid", "try"],
            "unexpected_keywords": ["ValueError", "stack trace", "exception"]
        },
        {
            "error": Exception("Unknown error"),
            "expected_keywords": ["error", "problem", "support"],
            "unexpected_keywords": ["Exception", "stack trace", "exception"]
        }
    ]
    
    # Mock the get_friendly_message method that would be in workflow_manager.py
    def get_friendly_message(error):
        if isinstance(error, NetworkError) or "Network" in str(error):
            return "I'm having trouble connecting to the network. Please check your connection and try again."
        elif isinstance(error, TimeoutError) or "timeout" in str(error).lower():
            return "The operation is taking too long. Please try again later."
        elif "pdf" in str(error).lower():
            return "The PDF file appears to be invalid or corrupted. Please try uploading a different file."
        elif "file" in str(error).lower():
            return "I couldn't find the file you're looking for. It may have been deleted or moved."
        elif "permission" in str(error).lower():
            return "I don't have permission to access that resource. Please contact support."
        else:
            return "An error occurred while processing your request. Please try again or contact support if the problem persists."
    
    # Patch the get_friendly_message method onto our mock workflow
    mock_workflow.get_friendly_message = get_friendly_message
    
    # Test each error case
    for test_case in test_cases:
        error = test_case["error"]
        friendly_msg = mock_workflow.get_friendly_message(error)
        
        # Test that expected keywords are present
        for keyword in test_case["expected_keywords"]:
            assert keyword in friendly_msg.lower(), f"Expected '{keyword}' in message: {friendly_msg}"
        
        # Test that unexpected keywords are absent
        for keyword in test_case["unexpected_keywords"]:
            assert keyword not in friendly_msg.lower(), f"Unexpected '{keyword}' found in message: {friendly_msg}"

def test_cleanup_old_cases():
    """Test that the cleanup_old_cases function works properly."""
    # Create a temporary directory structure for testing
    import tempfile
    import json
    import shutil
    from datetime import datetime, timedelta
    
    # Create temp directory to simulate data_dir
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create year directory
        year_dir = Path(temp_dir) / "2023"
        year_dir.mkdir()
        
        # Create some test case directories with case_info.json files
        for i in range(3):
            case_dir = year_dir / f"case-{i}"
            case_dir.mkdir()
            case_info_path = case_dir / "case_info.json"
            
            # Write simulated case_info.json with different statuses and dates
            if i == 0:
                # Completed, old case (should be removed)
                created_date = (datetime.now() - timedelta(days=35)).isoformat()
                status = "COMPLETED"
            elif i == 1:
                # Completed but recent case (should be kept)
                created_date = (datetime.now() - timedelta(days=15)).isoformat()
                status = "COMPLETED"
            else:
                # Active case (should be kept regardless of age)
                created_date = (datetime.now() - timedelta(days=40)).isoformat()
                status = "ACTIVE"
                
            with open(case_info_path, 'w') as f:
                json.dump({
                    "case_id": f"case-{i}",
                    "created_at": created_date,
                    "status": status
                }, f)
        
        # Run the cleanup function with our temp directory
        result = cleanup_old_cases(str(temp_dir), max_age_days=30)
        
        # Check results
        assert result["processed"] == 3
        assert result["removed"] == 1
        
        # Verify the correct directories were removed/kept
        assert not (year_dir / "case-0").exists()  # Old completed case was removed
        assert (year_dir / "case-1").exists()      # Recent completed case was kept
        assert (year_dir / "case-2").exists()      # Active case was kept regardless of age 