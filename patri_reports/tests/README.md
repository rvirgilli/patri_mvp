# Patri Reports Testing Guide

This directory contains unit tests for the Patri Reports Telegram Assistant.

## Running Tests

You can run tests using the provided script or directly with pytest:

```bash
# Using the run_tests.py script:
python run_tests.py -v             # Run all tests with verbose output
python run_tests.py --whisper -v   # Run only Whisper API tests
python run_tests.py --llm -v       # Run only LLM-related tests
python run_tests.py --all -v       # Run all tests including failing ones
python run_tests.py --anthropic -v # Run tests with Anthropic API enabled

# Using pytest directly:
pytest patri_reports/tests/

# Run with verbose output:
pytest -v patri_reports/tests/

# Run a specific test file:
pytest patri_reports/tests/test_whisper.py

# Run a specific test:
pytest patri_reports/tests/test_llm_api.py::TestLLMAPI::test_generate_summary_success
```

## Test Structure

The tests are organized into the following categories:

### API Tests

- `test_whisper.py`: Tests for audio transcription API (consolidated from previous unittest and pytest versions)
- `test_llm_api.py`: Tests for OpenAI LLM API
- `test_anthropic_api.py`: Tests for Anthropic Claude API

### Core Functionality Tests

- `test_workflow_manager.py`: Tests for the core workflow functionality
- `test_workflow_manager_llm.py`: Tests for LLM-specific workflow functionality
- `test_case_manager.py`: Tests for case data management
- `test_state_manager.py`: Tests for application state management

### Other Tests

- `test_pdf_processor.py`: Tests for PDF processing functionality
- `test_pdf_integration.py`: Integration tests with real PDF files
- `test_telegram_client.py`: Tests for Telegram client interface
- `test_config.py`: Tests for environment configuration

### Known Issues

Some tests in `test_workflow_manager.py` are currently failing and are skipped by default:
- `test_collection_state_handles_finish_button`
- `test_collection_state_handles_finish_button_wrong_case`
- `test_collection_state_handles_text_evidence`
- `test_collection_state_handles_photo_evidence`
- `test_collection_state_handles_voice_evidence`
- `test_finish_collection_workflow_success`
- `test_finish_collection_workflow_state_fails`

## Test Maintenance Notes

### Whisper API Tests

The Whisper API tests were previously split between unittest-style (`test_whisper_api.py`) and pytest-style (`test_api_whisper.py`) implementations. These have been consolidated into a single pytest-based file (`test_whisper.py`) that:

- Uses pytest fixtures and assertions
- Includes setup and teardown methods to manage test resources
- Tests both public API and internal implementation details
- Covers a full range of success and error cases

This consolidation ensures more maintainable tests while preserving complete test coverage.

## Environment Configuration for Testing

To test with different API providers, set the following environment variables:

```bash
# To use Anthropic Claude:
export USE_ANTHROPIC=true
export ANTHROPIC_API_KEY=your_api_key_here

# To use OpenAI:
export USE_ANTHROPIC=false  # or unset this variable
export OPENAI_API_KEY=your_api_key_here

# For WhisperAPI:
export OPENAI_API_KEY=your_api_key_here  # Same key for OpenAI and Whisper API
```

## Testing with Real API Keys

To test with real API keys, you'll need to modify the tests to use actual API keys:

```python
# Example for testing with real OpenAI API
import os
os.environ["OPENAI_API_KEY"] = "your_actual_api_key"
from patri_reports.api.llm import LLMAPI

# Call the API
api = LLMAPI()
result = api.generate_summary(case_data)
print(result)
```

**Warning**: Be careful with these tests as they consume API credits and may incur costs.

## Test Coverage

To check test coverage:

```bash
# Install coverage
pip install coverage

# Run tests with coverage
python run_tests.py -c

# Or directly:
coverage run -m pytest patri_reports/tests/

# Generate coverage report
coverage report -m
``` 