from enum import Enum, auto
import json
import os
import logging
import tempfile
import shutil
from typing import Optional

logger = logging.getLogger(__name__)

# Use strings for enum values for better JSON serialization/readability
class AppState(Enum):
    IDLE = "IDLE"
    WAITING_FOR_PDF = "WAITING_FOR_PDF"
    EVIDENCE_COLLECTION = "EVIDENCE_COLLECTION"

class StateManager:
    def __init__(self, state_file="app_state.json"):
        """
        Initializes the StateManager.

        Args:
            state_file (str): The path to the file used for persisting state.
        """
        self.state_file = state_file
        self._current_state = AppState.IDLE
        self._active_case_id: Optional[str] = None # Add active case id
        self._metadata = {}  # Dictionary to store additional metadata
        self._load_state()

    def _load_state(self):
        """Loads the application state (mode and active case ID) from the state file."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    state_name = data.get("current_mode") # Changed key to current_mode
                    self._active_case_id = data.get("active_case_id") # Load case_id
                    self._metadata = data.get("metadata", {})  # Load metadata with empty dict as default

                    if state_name and hasattr(AppState, state_name):
                        self._current_state = AppState[state_name]
                        logger.info(f"Successfully loaded state: {self._current_state}, Case ID: {self._active_case_id}")
                        # Validate consistency: if in collection mode, case_id should exist
                        if self._current_state == AppState.EVIDENCE_COLLECTION and not self._active_case_id:
                             logger.warning(f"Loaded EVIDENCE_COLLECTION state but active_case_id is missing. Resetting to IDLE.")
                             self._current_state = AppState.IDLE
                             self._active_case_id = None
                             self._metadata = {}  # Clear metadata
                             self._save_state() # Save corrected state
                    else:
                        logger.warning(f"Invalid or missing state name '{state_name}' in {self.state_file}. Defaulting to IDLE.")
                        self._current_state = AppState.IDLE
                        self._active_case_id = None
                        self._metadata = {}  # Clear metadata
                        self._save_state() # Save default state
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Error loading state from {self.state_file}: {e}. Defaulting to IDLE.")
                self._current_state = AppState.IDLE
                self._active_case_id = None
                self._metadata = {}  # Clear metadata
        else:
            logger.info(f"State file {self.state_file} not found. Initializing with default state: {self._current_state}.")
            self._save_state() # Save initial state

    def _save_state(self):
        """Saves the current application state (mode and active case ID) using atomic write."""
        state_data = {
            "current_mode": self._current_state.name, # Use name for consistency
            "active_case_id": self._active_case_id,
            "metadata": self._metadata  # Save metadata
        }
        temp_fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(self.state_file), prefix=".tmp-")
        try:
            with os.fdopen(temp_fd, 'w') as temp_f:
                json.dump(state_data, temp_f, indent=4)
            # Atomic replace
            shutil.move(temp_path, self.state_file)
            logger.debug(f"State saved: {self._current_state}, Case ID: {self._active_case_id}")
        except (IOError, OSError) as e:
            logger.error(f"Error saving state to {self.state_file}: {e}")
            # Clean up temporary file if move failed
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError as remove_e:
                    logger.error(f"Error removing temporary state file {temp_path}: {remove_e}")
        finally:
            # Ensure temp file is removed if it still exists (e.g., error before move)
            if os.path.exists(temp_path):
                 try:
                     os.remove(temp_path)
                 except OSError as remove_e:
                     logger.error(f"Error removing temporary state file {temp_path} in finally block: {remove_e}")

    def get_state(self) -> AppState:
        """Returns the current application state mode."""
        return self._current_state

    def get_active_case_id(self) -> Optional[str]:
        """Returns the active case ID, if one exists."""
        return self._active_case_id
        
    def get_metadata(self, key: str = None):
        """
        Gets metadata stored in the state manager.
        
        Args:
            key: Optional key to retrieve specific metadata value.
                If None, returns the entire metadata dictionary.
                
        Returns:
            The requested metadata value, or the entire metadata dictionary if key is None.
            If the key doesn't exist, returns None.
        """
        if key is None:
            return self._metadata.copy()  # Return a copy to prevent direct modification
        return self._metadata.get(key)
        
    def set_metadata(self, metadata_dict: dict = None, **kwargs):
        """
        Sets metadata in the state manager.
        
        This can be called either with a dictionary or with key-value pairs.
        
        Args:
            metadata_dict: Optional dictionary of metadata to update.
            **kwargs: Key-value pairs to update in the metadata.
            
        Examples:
            set_metadata({"key1": "value1", "key2": "value2"})
            set_metadata(key1="value1", key2="value2")
        """
        if metadata_dict is not None:
            self._metadata.update(metadata_dict)
        if kwargs:
            self._metadata.update(kwargs)
        self._save_state()

    def set_state(self, new_state: AppState, active_case_id: Optional[str] = None):
        """
        Sets the application state (mode and optionally active case ID).

        Args:
            new_state (AppState): The desired new state mode.
            active_case_id (Optional[str]): The case ID to set if entering a case-specific state.
                                           Should be None if transitioning to IDLE.

        Returns:
            bool: True if the state transition was successful, False otherwise.
        """
        if not isinstance(new_state, AppState):
            logger.error(f"Invalid state type provided: {type(new_state)}")
            return False

        # Basic validation for case_id based on new_state
        if new_state == AppState.EVIDENCE_COLLECTION and not active_case_id:
            logger.error("Attempted to set state to EVIDENCE_COLLECTION without an active_case_id.")
            return False
        if new_state != AppState.EVIDENCE_COLLECTION and active_case_id is not None:
             logger.warning(f"Setting state to {new_state} but an active_case_id ('{active_case_id}') was provided. Clearing case ID.")
             active_case_id = None # Ensure case_id is cleared when not in collection mode

        if self._is_valid_transition(new_state):
            old_state = self._current_state
            old_case_id = self._active_case_id
            self._current_state = new_state
            self._active_case_id = active_case_id # Set the new case ID
            
            # Reset metadata when transitioning to IDLE
            if new_state == AppState.IDLE:
                self._metadata = {}
                
            logger.info(f"State transitioned from {old_state} (Case: {old_case_id}) to {self._current_state} (Case: {self._active_case_id})")
            self._save_state()
            return True
        else:
            logger.warning(f"Invalid state transition attempted: {self._current_state} -> {new_state}")
            return False

    def _is_valid_transition(self, new_state: AppState) -> bool:
        """
        Checks if transitioning to the new state is valid based on the current state.
        Define the allowed transitions here.
        """
        # Example transitions (customize as needed)
        valid_transitions = {
            AppState.IDLE: [AppState.WAITING_FOR_PDF],
            AppState.WAITING_FOR_PDF: [AppState.EVIDENCE_COLLECTION, AppState.IDLE], # Can go back to IDLE if PDF is invalid/cancelled
            AppState.EVIDENCE_COLLECTION: [AppState.IDLE] # Cycle completes back to IDLE
        }

        allowed_next_states = valid_transitions.get(self._current_state, [])
        return new_state in allowed_next_states

# Example usage (optional, for testing)
if __name__ == "__main__":
    # Configure logging for testing
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Test StateManager
    state_manager = StateManager("test_app_state.json")
    print(f"Initial state: {state_manager.get_state()}")

    # Attempt valid transitions
    state_manager.set_state(AppState.WAITING_FOR_PDF)
    print(f"State after set WAITING_FOR_PDF: {state_manager.get_state()}")

    state_manager.set_state(AppState.EVIDENCE_COLLECTION)
    print(f"State after set EVIDENCE_COLLECTION: {state_manager.get_state()}")

    # Attempt invalid transition
    state_manager.set_state(AppState.WAITING_FOR_PDF) # Invalid from EVIDENCE_COLLECTION
    print(f"State after attempting invalid transition: {state_manager.get_state()}")

    # Complete cycle
    state_manager.set_state(AppState.IDLE)
    print(f"State after set IDLE: {state_manager.get_state()}")

    # Clean up test file
    if os.path.exists("test_app_state.json"):
        os.remove("test_app_state.json")
        print("Cleaned up test_app_state.json")

    # Test recovery
    print("Testing recovery...")
    state_manager_2 = StateManager("test_app_state_recovery.json")
    state_manager_2.set_state(AppState.WAITING_FOR_PDF) # Save state
    print(f"State saved: {state_manager_2.get_state()}")
    del state_manager_2 # Simulate shutdown

    state_manager_3 = StateManager("test_app_state_recovery.json") # Reload
    print(f"State loaded on recovery: {state_manager_3.get_state()}")
    if os.path.exists("test_app_state_recovery.json"):
        os.remove("test_app_state_recovery.json")
        print("Cleaned up test_app_state_recovery.json") 