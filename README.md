# Patri Reports Telegram Assistant

A modular, button-driven Telegram bot for forensic case management and evidence collection, with LLM-powered summaries and checklists.

**Core Philosophy:**
- Strictly button-driven workflow (no conversational AI or free-text commands for control)
- Only one active case at a time; state is persisted and recoverable after restarts
- All data (PDFs, photos, audio, metadata) is stored locally in a structured directory
- Robust error handling and user-friendly feedback throughout the workflow

## Features
- **Deterministic, button-driven Telegram interface** for starting new cases and collecting evidence
- **Case and state management** with persistent storage and automatic recovery
- **Evidence collection:**
  - Text notes
  - Photos (with optional fingerprint tagging)
  - Audio notes (transcribed automatically via Whisper API)
- **LLM integration** (OpenAI & Anthropic Claude) for generating case summaries and evidence checklists from PDF data
- **PDF processing** to extract structured information from occurrence reports
- **Admin notifications and user access control**
- **Local storage**: All case data and evidence files are saved on the server running the bot
- **Clear, contextual feedback** and robust error handling for users

## Setup
1. **Clone the repository and enter the project directory.**
2. **Create a virtual environment and activate it:**
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```
3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
4. **Create a `.env` file** in the root directory with at least:
   ```env
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token
   ALLOWED_TELEGRAM_USERS=123456789,987654321  # Comma-separated Telegram user IDs
   LOG_LEVEL=INFO  # Optional, defaults to INFO
   # For LLM integration:
   OPENAI_API_KEY=your_openai_key
   # Or for Anthropic Claude:
   ANTHROPIC_API_KEY=your_anthropic_key
   USE_ANTHROPIC=true
   ```

## Running the Bot
Run the Telegram bot:
```bash
python -m patri_reports.main run
```

## Testing
Run all tests with the provided script:
```bash
python run_tests.py -v
```
- For coverage: `python run_tests.py -c`
- For specific APIs: `python run_tests.py --llm` or `--whisper`
- For Anthropic: `python run_tests.py --anthropic`

Or use pytest directly:
```bash
pytest patri_reports/tests/
```

## Project Structure
- `patri_reports/` — Main application code
  - `main.py` — Entry point
  - `telegram_client.py` — Telegram bot logic
  - `workflow/` — Workflow and evidence collection logic
  - `api/` — LLM and external API integrations
  - `models/` — Data models
  - `utils/` — Utilities and config
  - `tests/` — Test suite
- `run_tests.py` — Test runner script
- `.env` — Environment variables (not committed)
- `data/` — All case data and evidence files are stored here

---
For more details, see the code, module docstrings, and `documentation.md`.