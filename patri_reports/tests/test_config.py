import pytest
import os
# We need importlib to reload the config module in tests
import importlib 
# We need mocker to prevent load_dotenv from reloading .env during tests
# Note: Assumes pytest-mock is installed (add it to requirements.txt if not)

# Adjust the path to import from the correct directory
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Import the module we are testing
from patri_reports.utils import config

# Environment variable names used in the tests
TEST_VAR_1 = "TEST_ENV_VAR_1"
TEST_VAR_2 = "TEST_ENV_VAR_2"

@pytest.fixture(autouse=True)
def manage_env_vars(monkeypatch, mocker):
    """Set default environment variables needed for config import and mock load_dotenv."""
    # Mock load_dotenv to prevent it from overriding monkeypatched vars
    mocker.patch('dotenv.load_dotenv') # Patch globally for the test session initially

    # Set required vars to valid values before any test runs
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "initial_token")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USERS", "1")
    monkeypatch.setenv("LOG_LEVEL", "INFO") # Set optional to default

    # Reload config initially with mocked load_dotenv and base env vars
    # This ensures subsequent tests dealing with missing vars work correctly
    importlib.reload(config) 

    yield # Let the test run

    # Teardown: Clean up env vars (monkeypatch handles this automatically)
    # No need to manually delete if monkeypatch is used within tests or fixtures

def test_config_loading(monkeypatch, mocker):
    """Tests if environment variables are loaded correctly into config."""
    # Mock load_dotenv just in case (though fixture might cover it)
    mock_load_dotenv = mocker.patch('dotenv.load_dotenv')
    
    # Set specific values for this test
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token_123")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USERS", "12345, 67890")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    # Reload the config module to pick up the monkeypatched environment
    importlib.reload(config)
    
    # Assert that load_dotenv was not called during reload (because it's mocked)
    # This confirms our mock is working if needed, but not strictly necessary for the test logic
    # mock_load_dotenv.assert_not_called() 
    
    assert config.TELEGRAM_BOT_TOKEN == "test_token_123"
    assert config.ALLOWED_TELEGRAM_USERS == [12345, 67890]
    assert config.LOG_LEVEL == "DEBUG"

def test_config_defaults(monkeypatch, mocker):
    """Tests if default values are used when env vars are missing."""
    # Mock load_dotenv for this specific test's reload
    mocker.patch('dotenv.load_dotenv')
    
    # Ensure required vars are set
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "default_test_token")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USERS", "99999")
    # Ensure LOG_LEVEL is *not* set for this test
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    
    # Reload the config module to pick up the modified environment
    importlib.reload(config)
    
    assert config.LOG_LEVEL == "INFO" # Check default

def test_missing_required_vars(monkeypatch, mocker):
    """Tests if ValueError is raised when required env vars are missing."""
    # Mock load_dotenv to prevent it reading from .env during reload
    mocker.patch('dotenv.load_dotenv')

    # --- Test missing TELEGRAM_BOT_TOKEN ---
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("ALLOWED_TELEGRAM_USERS", "123") # Keep users set

    with pytest.raises(ValueError, match="Missing required environment variable: TELEGRAM_BOT_TOKEN"):
        importlib.reload(config) # Reload to trigger the check

    # --- Test missing ALLOWED_TELEGRAM_USERS ---
    # Reset token, remove users
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy_token")
    monkeypatch.delenv("ALLOWED_TELEGRAM_USERS", raising=False)
    
    with pytest.raises(ValueError, match="Missing or invalid required environment variable: ALLOWED_TELEGRAM_USERS"):
        importlib.reload(config) # Reload to trigger the check

def test_invalid_user_ids(monkeypatch, mocker):
    """Tests handling of invalid non-integer user IDs."""
    # Mock load_dotenv
    mocker.patch('dotenv.load_dotenv')

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token_invalid_users")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USERS", "123,abc,456")
    monkeypatch.delenv("LOG_LEVEL", raising=False) # Use default log level

    # The config code currently prints an error and results in an empty ALLOWED_TELEGRAM_USERS list.
    # This empty list then triggers the "Missing or invalid required environment variable" check.
    with pytest.raises(ValueError, match="Missing or invalid required environment variable: ALLOWED_TELEGRAM_USERS"):
        importlib.reload(config) 