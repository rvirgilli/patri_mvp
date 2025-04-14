# Patri MVP

Minimal Viable Product for the Patri project.

## Setup

1.  Create a virtual environment:
    ```bash
    python -m venv venv
    source venv/bin/activate
    ```
2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
3.  Create a `.env` file based on the structure in `src/patri_mvp/config.py` (or copy `.env.example` if one exists) and populate the required environment variables:
    ```env
    TELEGRAM_BOT_TOKEN=your_telegram_bot_token
    ALLOWED_TELEGRAM_USERS=user_id1,user_id2
    LOG_LEVEL=INFO # Optional, defaults to INFO
    ```

## LLM Integration

The application supports multiple LLM providers for generating case summaries and checklists:

### OpenAI (Default)

Set the `OPENAI_API_KEY` environment variable to use OpenAI's GPT models:

```bash
export OPENAI_API_KEY=your_api_key_here
```

### Anthropic Claude

To use Anthropic's Claude models, set both the API key and enable Anthropic usage:

```bash
export ANTHROPIC_API_KEY=your_api_key_here
export USE_ANTHROPIC=true
```

The system will automatically fall back to OpenAI if Anthropic API calls fail.

## Running Tests

Run the tests using the provided test runner script:

```bash
# Run all tests
./run_tests.py

# Run with verbose output
./run_tests.py -v

# Run with coverage report
./run_tests.py -c

# Run a specific test file
./run_tests.py -t patri_reports/tests/test_llm_api.py

# Run tests with Anthropic enabled
./run_tests.py --anthropic
```

See `patri_reports/tests/README.md` for more detailed testing instructions.