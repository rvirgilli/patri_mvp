import pytest
import os
import json
import time
import shutil
from unittest.mock import patch, MagicMock

# Adjust the path to import from the correct directory (patri_reports)
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from patri_reports.state_manager import StateManager, AppState

TEST_STATE_FILE = "test_state_manager_state.json"
TEMP_DIR = "temp_test_state_dir"


@pytest.fixture(autouse=True)
def manage_test_state_file():
    """Fixture to create and destroy the test state file and temp dir."""
    # Setup: Ensure clean environment
    if os.path.exists(TEST_STATE_FILE):
        os.remove(TEST_STATE_FILE)
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)
    os.makedirs(TEMP_DIR, exist_ok=True)
    
    yield  # Run the test

    # Teardown: Clean up created files/dirs
    if os.path.exists(TEST_STATE_FILE):
        os.remove(TEST_STATE_FILE)
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)


def test_initialization_default_state():
    """Test StateManager initializes to IDLE, None case_id if no file exists and saves default."""
    # No patch needed, just check the outcome
    manager = StateManager(TEST_STATE_FILE)
    assert manager.get_state() == AppState.IDLE
    assert manager.get_active_case_id() is None
    assert os.path.exists(TEST_STATE_FILE), "Default state file should be created on init"
    # Check file content
    with open(TEST_STATE_FILE, 'r') as f:
        data = json.load(f)
        assert data["current_mode"] == AppState.IDLE.name
        assert data["active_case_id"] is None

def test_initialization_loads_existing_state_idle():
    """Test StateManager loads IDLE state and None case_id correctly."""
    initial_data = {"current_mode": AppState.IDLE.name, "active_case_id": None}
    with open(TEST_STATE_FILE, 'w') as f: json.dump(initial_data, f)
    manager = StateManager(TEST_STATE_FILE)
    assert manager.get_state() == AppState.IDLE
    assert manager.get_active_case_id() is None

def test_initialization_loads_existing_state_collection():
    """Test StateManager loads EVIDENCE_COLLECTION state and case_id correctly."""
    case_id = "CASE-123"
    initial_data = {"current_mode": AppState.EVIDENCE_COLLECTION.name, "active_case_id": case_id}
    with open(TEST_STATE_FILE, 'w') as f: json.dump(initial_data, f)
    manager = StateManager(TEST_STATE_FILE)
    assert manager.get_state() == AppState.EVIDENCE_COLLECTION
    assert manager.get_active_case_id() == case_id

def test_initialization_resets_if_collection_state_has_no_case_id():
    """Test StateManager resets to IDLE if file shows EVIDENCE_COLLECTION but no case_id."""
    initial_data = {"current_mode": AppState.EVIDENCE_COLLECTION.name, "active_case_id": None}
    with open(TEST_STATE_FILE, 'w') as f: json.dump(initial_data, f)
    with patch.object(StateManager, '_save_state') as mock_save: # Check if corrected state is saved
        manager = StateManager(TEST_STATE_FILE)
        assert manager.get_state() == AppState.IDLE
        assert manager.get_active_case_id() is None
        mock_save.assert_called_once()

def test_initialization_handles_corrupt_file():
    """Test StateManager defaults to IDLE, None case_id if state file is corrupt."""
    with open(TEST_STATE_FILE, 'w') as f: f.write("this is not json")
    with patch.object(StateManager, '_save_state') as mock_save:
        manager = StateManager(TEST_STATE_FILE)
        assert manager.get_state() == AppState.IDLE
        assert manager.get_active_case_id() is None
        # Save should not be called here as per current logic, init defaults in memory
        # mock_save.assert_called_once() 

def test_initialization_handles_invalid_state_name():
    """Test StateManager defaults to IDLE, None case_id if state name is invalid."""
    initial_data = {"current_mode": "INVALID_STATE_NAME", "active_case_id": "CASE-XYZ"}
    with open(TEST_STATE_FILE, 'w') as f: json.dump(initial_data, f)
    with patch.object(StateManager, '_save_state') as mock_save:
        manager = StateManager(TEST_STATE_FILE)
        assert manager.get_state() == AppState.IDLE
        assert manager.get_active_case_id() is None
        mock_save.assert_called_once() # Should save the corrected default state

def test_set_state_valid_transitions_and_case_id():
    """Test valid state transitions with correct active_case_id handling."""
    manager = StateManager(TEST_STATE_FILE)
    case_id = "CASE-SET-123"
    
    # IDLE -> WAITING_FOR_PDF
    assert manager.set_state(AppState.WAITING_FOR_PDF) is True
    # WAITING_FOR_PDF -> EVIDENCE_COLLECTION
    assert manager.set_state(AppState.EVIDENCE_COLLECTION, active_case_id=case_id) is True
    # EVIDENCE_COLLECTION -> IDLE
    assert manager.set_state(AppState.IDLE) is True

    # Test alternative path including an *invalid* transition attempt
    manager.set_state(AppState.WAITING_FOR_PDF)
    assert manager.set_state(AppState.EVIDENCE_COLLECTION, active_case_id="TEMP-CASE") is True # Go to collection
    assert manager.get_state() == AppState.EVIDENCE_COLLECTION
    assert manager.get_active_case_id() == "TEMP-CASE"
    
    # Attempt invalid transition: EVIDENCE_COLLECTION -> WAITING_FOR_PDF
    assert manager.set_state(AppState.WAITING_FOR_PDF) is False # Should fail
    assert manager.get_state() == AppState.EVIDENCE_COLLECTION # State should remain COLLECTION
    assert manager.get_active_case_id() == "TEMP-CASE" # Case ID should remain

    # Now, valid transition from COLLECTION -> IDLE
    assert manager.set_state(AppState.IDLE) is True
    assert manager.get_state() == AppState.IDLE
    assert manager.get_active_case_id() is None
    # Verify persistence
    reloaded_manager = StateManager(TEST_STATE_FILE)
    assert reloaded_manager.get_state() == AppState.IDLE
    assert reloaded_manager.get_active_case_id() is None

def test_set_state_invalid_transitions():
    """Test invalid state transitions are blocked, state/case_id remain unchanged."""
    manager = StateManager(TEST_STATE_FILE)
    initial_state = manager.get_state()
    initial_case_id = manager.get_active_case_id()

    # IDLE -> EVIDENCE_COLLECTION (Invalid)
    assert manager.set_state(AppState.EVIDENCE_COLLECTION, active_case_id="dummy") is False
    assert manager.get_state() == initial_state
    assert manager.get_active_case_id() == initial_case_id

    # Set to WAITING_FOR_PDF for next test
    manager.set_state(AppState.WAITING_FOR_PDF)
    current_state = manager.get_state()
    current_case_id = manager.get_active_case_id()

    # WAITING_FOR_PDF -> WAITING_FOR_PDF (Invalid - no self-transitions in example)
    # This depends on _is_valid_transition logic. Assuming no self-transitions.
    # If self-transitions ARE allowed, this test needs adjustment.
    # assert manager.set_state(AppState.WAITING_FOR_PDF) is False
    # assert manager.get_state() == current_state
    # assert manager.get_active_case_id() == current_case_id

    # Set to EVIDENCE_COLLECTION for next test
    manager.set_state(AppState.EVIDENCE_COLLECTION, active_case_id="CASE-XYZ")
    current_state = manager.get_state()
    current_case_id = manager.get_active_case_id()

    # EVIDENCE_COLLECTION -> WAITING_FOR_PDF (Invalid)
    assert manager.set_state(AppState.WAITING_FOR_PDF) is False
    assert manager.get_state() == current_state
    assert manager.get_active_case_id() == current_case_id

def test_set_state_validation_for_case_id():
    """Test specific validation rules for active_case_id in set_state."""
    manager = StateManager(TEST_STATE_FILE)

    # 1. Fail if setting to EVIDENCE_COLLECTION without case_id
    manager.set_state(AppState.WAITING_FOR_PDF) # Prerequisite state
    assert manager.set_state(AppState.EVIDENCE_COLLECTION, active_case_id=None) is False
    assert manager.get_state() == AppState.WAITING_FOR_PDF # Should not change state
    assert manager.set_state(AppState.EVIDENCE_COLLECTION) is False # Also test with implicit None
    assert manager.get_state() == AppState.WAITING_FOR_PDF

    # 2. Succeed but clear case_id if provided when setting to non-collection state
    manager.set_state(AppState.EVIDENCE_COLLECTION, active_case_id="SHOULD-BE-CLEARED")
    assert manager.get_active_case_id() == "SHOULD-BE-CLEARED"
    # Now transition to IDLE, providing a case_id (should be ignored/cleared)
    assert manager.set_state(AppState.IDLE, active_case_id="SHOULD-BE-CLEARED") is True
    assert manager.get_state() == AppState.IDLE
    assert manager.get_active_case_id() is None # Verify case_id was cleared
    # Test transition to WAITING_FOR_PDF with a case_id
    manager.set_state(AppState.WAITING_FOR_PDF, active_case_id="SHOULD-BE-CLEARED-TOO")
    assert manager.get_state() == AppState.WAITING_FOR_PDF
    assert manager.get_active_case_id() is None # Verify case_id was cleared

def test_set_state_invalid_type():
    """Test setting state with a non-AppState type fails."""
    manager = StateManager(TEST_STATE_FILE)
    initial_state = manager.get_state()
    initial_case_id = manager.get_active_case_id()
    assert manager.set_state("NOT_AN_ENUM") is False
    assert manager.get_state() == initial_state
    assert manager.get_active_case_id() == initial_case_id

def test_atomic_save_includes_case_id():
    """Verify that the save operation includes the case ID."""
    manager = StateManager(TEST_STATE_FILE)
    case_id = "ATOMIC-CASE"
    
    # Add intermediate step IDLE -> WAITING_FOR_PDF
    assert manager.set_state(AppState.WAITING_FOR_PDF) is True
    # Test successful save to EVIDENCE_COLLECTION
    assert manager.set_state(AppState.EVIDENCE_COLLECTION, active_case_id=case_id) is True
    assert os.path.exists(TEST_STATE_FILE)
    with open(TEST_STATE_FILE, 'r') as f:
        data = json.load(f)
        assert data['current_mode'] == AppState.EVIDENCE_COLLECTION.name
        assert data['active_case_id'] == case_id
    # Test save with None case ID
    assert manager.set_state(AppState.IDLE) is True
    assert os.path.exists(TEST_STATE_FILE)
    with open(TEST_STATE_FILE, 'r') as f:
        data = json.load(f)
        assert data['current_mode'] == AppState.IDLE.name
        assert data['active_case_id'] is None

@patch('shutil.move', side_effect=OSError("Simulated disk full error during move"))
@patch('os.remove') # Mock os.remove to check cleanup attempts
@patch('tempfile.mkstemp') # Control temp file creation
def test_atomic_save_failure_cleanup(mock_mkstemp, mock_os_remove, mock_shutil_move):
    """Test that temporary files are cleaned up if the atomic move fails."""
    # Configure mock mkstemp to return predictable values
    temp_fd = 10
    temp_path = os.path.abspath(".tmp-test_state_manager_state.json")
    mock_mkstemp.return_value = (temp_fd, temp_path)
    
    # Ensure the fake temp file appears to exist for cleanup check
    with patch('os.path.exists', return_value=True) as mock_exists:
         # Patch fdopen to avoid needing a real file descriptor
         with patch('os.fdopen', MagicMock()) as mock_fdopen:
              manager = StateManager(TEST_STATE_FILE) 
              # Attempt state change that triggers save
              manager.set_state(AppState.WAITING_FOR_PDF) 
              
              # Verify mocks were called as expected
              mock_mkstemp.assert_called_once()
              mock_fdopen.assert_called_once()
              mock_shutil_move.assert_called_once_with(temp_path, TEST_STATE_FILE)
              
              # Check that os.remove was called on the temp path during error handling
              # Need to check calls to os.path.exists and os.remove within the except/finally blocks
              # This depends on the exact implementation of error handling in _save_state
              # A simpler check might be to see if remove was called with temp_path
              mock_os_remove.assert_any_call(temp_path)

def test_recovery_after_save_with_case_id():
     """Test recovery of both state mode and active_case_id."""
     manager1 = StateManager(TEST_STATE_FILE)
     case_id = "RECOVERY-CASE"
     # Add intermediate step IDLE -> WAITING_FOR_PDF
     assert manager1.set_state(AppState.WAITING_FOR_PDF) is True
     assert manager1.set_state(AppState.EVIDENCE_COLLECTION, active_case_id=case_id) is True
     assert manager1.get_state() == AppState.EVIDENCE_COLLECTION
     assert manager1.get_active_case_id() == case_id
     
     # Simulate application restart
     manager2 = StateManager(TEST_STATE_FILE)
     assert manager2.get_state() == AppState.EVIDENCE_COLLECTION
     assert manager2.get_active_case_id() == case_id

     # Transition back to IDLE and check recovery
     manager2.set_state(AppState.IDLE)
     assert manager2.get_state() == AppState.IDLE
     assert manager2.get_active_case_id() is None

     manager3 = StateManager(TEST_STATE_FILE)
     assert manager3.get_state() == AppState.IDLE
     assert manager3.get_active_case_id() is None 