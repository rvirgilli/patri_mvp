Okay, here is a refined and detailed documentation proposal for the simplified, button-driven Patri Reports Telegram application you're aiming to develop as an MVP.

---

# Patri Reports Telegram Assistant - MVP Documentation

## 1. Introduction

This document outlines the design, scope, and functionality of the **Patri Reports Telegram Assistant (MVP)**. This application serves as a streamlined, deterministic tool for forensic experts to initiate forensic cases based on occurrence PDFs and collect preliminary evidence directly via a Telegram bot interface.

**Core Philosophy:** This MVP prioritizes simplicity, reliability, and a tightly controlled workflow over the flexibility of a conversational AI agent. It operates as a single, standalone Python application using a **button-driven interface** within Telegram to guide the user through fixed processes. All case data and evidence files are stored **locally** on the server running the application.

**Target User:** Forensic Expert.

**Key Distinction from Original Plan:** This MVP intentionally removes the complexities of the LangChain LLM agent, MCP communication, microservices (Telegram Gateway, Case Management Server), and cloud storage (Google Drive) to establish a stable core foundation first.

## 2. MVP Objectives

*   Provide a reliable Telegram bot interface for forensic case initiation and evidence collection.
*   Guide users strictly through **predefined workflows** using interactive **Telegram buttons**.
*   Handle the initiation of **one active case at a time**.
*   Accept standardized forensic occurrence **PDFs** to trigger new case creation.
*   Perform basic **processing of the PDF** to extract key information into a structured format (local JSON file).
*   Utilize an **LLM** via API for specific, non-conversational tasks: generating an occurrence summary and a suggested evidence checklist based on extracted PDF data.
*   Store case metadata (JSON) and associated files (PDF, photos, audio) **locally** in a structured directory format.
*   Record key timestamps: `case_received`, `attendance_started`, `collection_finished`.
*   Allow users to submit **text notes, photos, and audio notes** as evidence during the active collection phase.
*   Use an **audio-to-text service (e.g., Whisper API)** to transcribe submitted audio notes, saving both the transcript and the original audio file.
*   Provide clear, contextual feedback to the user within Telegram (status updates, confirmations, summaries, checklists, location pins).
*   Reliably manage application state (`IDLE`, `WAITING_FOR_PDF`, `EVIDENCE_COLLECTION`) and persist the state (`active_case_id`, `current_mode`) across application restarts.

## 3. Scope

### In Scope (MVP):

*   **Single Application Architecture:** All logic contained within one Python application.
*   **Interface:** Telegram Bot (using `python-telegram-bot` or similar).
*   **Interaction Model:** Strictly **button-driven**. No free-text command parsing (except for sending evidence content itself).
*   **Primary Workflow:**
    *   Start new case via button press.
    *   Wait for and receive one occurrence PDF.
    *   Process PDF (basic extraction + LLM summary/checklist generation).
    *   Create local case structure (folders, JSON).
    *   Pin a Telegram message indicating the active case.
    *   Enter `EVIDENCE_COLLECTION` mode for the created case.
    *   Receive Text Notes, Photos, Audio Notes.
    *   Transcribe audio using an external API (e.g., Whisper).
    *   Allow tagging photos as "Fingerprint" via confirmation buttons post-upload.
    *   Record `case_received`, `attendance_started`, `collection_finished` timestamps.
    *   End evidence collection via button press.
    *   Return to `IDLE` state.
*   **State Management:** Persistent state (`current_mode`, `active_case_id`) stored locally (e.g., `app_state.json`). Ability to resume an active case on restart.
*   **Data Storage:** Local file system only (JSON for metadata, dedicated folders for PDF, photos, audio).
*   **External APIs:** Specific calls to LLM (summary/checklist) and Whisper (transcription).
*   **Testing:** Unit and basic integration tests for core components and workflow.

### Out of Scope (MVP):

*   Conversational LLM Agent (LangChain AgentExecutor).
*   Model Context Protocol (MCP) and separate MCP servers.
*   Microservice architecture.
*   Google Drive integration/backup.
*   Complex case queries (only resuming an active case is supported).
*   Handling multiple simultaneous active cases.
*   Free-text commands or natural language understanding beyond evidence submission.
*   Advanced evidence analysis or report generation.
*   User authentication/authorization beyond basic Telegram `ALLOWED_USERS`.
*   Web UI or other interfaces.

## 4. Architecture

The MVP operates as a single Python application interacting directly with the Telegram API and local storage.

```mermaid
graph TD
    User[Forensic Expert] -- Telegram UI --> TelegramAPI[Telegram Bot API]
    TelegramAPI -- Events (Messages, Buttons, Files) --> App[Patri Reports Telegram Assistant (Python App)]
    App -- API Calls --> TelegramAPI

    subgraph App [Patri Reports Telegram Assistant (Python App)]
        direction LR
        TGClient[Telegram Client Module] <--> WFManager[Workflow Manager]
        WFManager -- Uses --> CaseMgr[Case Manager]
        WFManager -- Uses --> StateMgr[State Manager (app_state.json)]
        WFManager -- Calls --> ExtAPI[External API Wrappers]
        CaseMgr -- Reads/Writes --> LocalStorage[Local File System (./data)]
    end

    App -- API Calls --> LLM_API[LLM API (Summary/Checklist)]
    App -- API Calls --> Whisper_API[Whisper API (Transcription)]

    style App fill:#f9f,stroke:#333,stroke-width:2px
```

*   **Telegram Client Module:** Interfaces with `python-telegram-bot`. Handles receiving updates (messages, button presses, files), sending messages/photos/locations/buttons, pinning messages, and translating Telegram events into calls for the Workflow Manager. Remains agnostic of business logic.
*   **Workflow Manager:** The core orchestrator. Manages application state (`IDLE`, `WAITING_FOR_PDF`, `EVIDENCE_COLLECTION`). Reacts to events from the Telegram Client based on the current state. Calls Case Manager and External APIs as needed per the defined workflow.
*   **State Manager:** Simple component responsible for loading/saving the application's persistent state (`current_mode`, `active_case_id`) to/from a local file (`app_state.json`).
*   **Case Manager:** Handles all operations related to case data persistence: creating/reading/updating the case JSON file, managing the local directory structure, saving evidence files (PDF, photo, audio), and running the PDF processing logic.
*   **External API Wrappers:** Modules dedicated to making calls to the LLM and Whisper APIs, handling request formatting and response parsing.
*   **Local File System:** The storage backend (`./data/` directory).

## 5. Core Workflow: New Case Initiation & Evidence Collection

1.  **Application Start:** Load state from `app_state.json`.
2.  **Initial State (`IDLE`):**
    *   Unpin any previously pinned message in the chat.
    *   If `active_case_id` is loaded (app restarted during collection): Send message "Resuming evidence collection for Case {active_case_id}." Transition to `EVIDENCE_COLLECTION` state (step 8). Show relevant evidence/finish buttons.
    *   If `active_case_id` is `null`: Send welcome message. Show "➕ Start New Case" button.
3.  **User Action:** Clicks "➕ Start New Case".
4.  **State Transition:** `IDLE` -> `WAITING_FOR_PDF`.
5.  **User Prompt:** Send message: "Please send the occurrence PDF report for the new case. Or click [Cancel]". Show "[Cancel]" button.
6.  **User Action:**
    *   Clicks "[Cancel]": Transition back to `IDLE` (step 2).
    *   Sends a PDF file: Proceed to step 7.
    *   Sends anything else: Ignore or reply "Please send a PDF file or click Cancel."
7.  **PDF Processing:**
    *   Receive PDF file via Telegram Client.
    *   Call `CaseManager.process_pdf(pdf_file_data)`.
    *   **If Success:**
        *   `process_pdf` returns structured JSON data (`case_info`).
        *   `CaseManager` creates local structure: `./data/<case_id>/`, saves `case_info.json`, saves `occurrence.pdf`.
        *   Record `case_received` timestamp in `case_info.json`.
        *   Call `ExternalAPI.generate_summary_and_checklist(case_info)` -> returns `summary`, `checklist`.
        *   Send messages to user:
            *   "✅ PDF processed successfully. Case ID: {case_id} created."
            *   (Summary message)
            *   (Checklist message)
            *   (Location pin message using coordinates from `case_info`)
        *   Pin a message: "📌 CASE {case_id} - Collecting Evidence".
        *   Proceed to step 8.
    *   **If Failure (PDF invalid, processing error):**
        *   Send error message: "❌ Could not process the PDF. Please ensure it's a valid report and try again, or Cancel."
        *   Remain in `WAITING_FOR_PDF` state (step 5).
8.  **State Transition:** -> `EVIDENCE_COLLECTION`. Update `app_state.json` with `mode` and `active_case_id`.
9.  **User Prompt:** Send message: "Ready to collect evidence for Case {case_id}. Send photos, audio voice notes, or text notes. Click [Finish Collection] when done." Show "[Finish Collection]" button.
10. **Evidence Loop (`EVIDENCE_COLLECTION` state):**
    *   **User Sends Text:**
        *   Record `attendance_started` timestamp (if first evidence).
        *   `CaseManager.add_text_evidence(active_case_id, text_content)`.
        *   Send confirmation: "💬 Text note added." Show evidence/finish buttons.
    *   **User Sends Photo:**
        *   Record `attendance_started` timestamp (if first evidence).
        *   `CaseManager.add_photo_evidence(active_case_id, photo_data)` -> returns `photo_id`.
        *   Send confirmation: "🖼️ Photo added (`{photo_id}`). Mark as fingerprint?" Show buttons: "[👍 Mark Fingerprint]", "[➕ Add More Evidence]", "[🏁 Finish Collection]".
    *   **User Sends Audio (Voice Note):**
        *   Record `attendance_started` timestamp (if first evidence).
        *   `CaseManager.save_audio_file(active_case_id, audio_data)` -> returns `audio_id`, `file_path`.
        *   Call `ExternalAPI.transcribe_audio(file_path)` -> returns `transcript`. Handle transcription errors.
        *   `CaseManager.add_audio_evidence(active_case_id, audio_id, transcript)`.
        *   Send confirmation: "🎤 Audio note added and transcribed: '{transcript snippet...}'." Show evidence/finish buttons.
    *   **User Clicks "[👍 Mark Fingerprint]" (after photo confirmation):**
        *   `CaseManager.update_evidence_metadata(active_case_id, "photo", photo_id, {"is_fingerprint": True})`.
        *   Send confirmation: "👍 Photo `{photo_id}` marked as fingerprint." Show evidence/finish buttons.
    *   **User Clicks "[➕ Add More Evidence]":**
        *   No state change. User can send next piece of evidence. Prompt may repeat "Ready for next evidence..."
    *   **User Clicks "[🏁 Finish Collection]":** Proceed to step 11.
    *   **User Sends Anything Else:** Ignore or prompt "Please send photo, audio, text, or click Finish."
11. **Finish Collection:**
    *   Record `collection_finished` timestamp in `case_info.json`.
    *   `CaseManager.finalize_case(active_case_id)` (e.g., save final JSON state).
    *   Unpin the "📌 CASE..." message.
    *   Send confirmation: "✅ Evidence collection finished for Case {case_id}."
12. **State Transition:** `EVIDENCE_COLLECTION` -> `IDLE`. Update `app_state.json` (`mode: "IDLE"`, `active_case_id: null`).
13. **Return to Idle:** Go back to step 2 (show welcome message and "➕ Start New Case" button).

## 6. State Management

*   **States:** Defined Enum (`IDLE`, `WAITING_FOR_PDF`, `EVIDENCE_COLLECTION`).
*   **Persistence:** `app_state.json` file storing `{ "current_mode": "STATE_ENUM", "active_case_id": "string_or_null" }`.
*   **Atomicity:** Updates to `app_state.json` should be atomic (write to temp file, then rename) to prevent corruption if the app crashes mid-write.
*   **Transitions:** Triggered strictly by specific, expected user actions (button presses, specific file types) within the correct originating state, as managed by the `Workflow Manager`.

## 7. Key Components Details

*   **`main.py`:** Initializes logging, loads config, creates instances of `TelegramClient`, `WorkflowManager`, etc., starts the Telegram bot polling/webhook.
*   **`config.py`:** Uses `pydantic-settings` or `python-dotenv` to load environment variables.
*   **`app_state.py`:** Defines `AppState` Enum, provides `load_state()` and `save_state(mode, active_case_id)` functions.
*   **`telegram_client/`:** Uses `python-telegram-bot`. `handlers.py` contains functions decorated with `@bot.message_handler`, `@bot.callback_query_handler`, etc. These handlers validate the update context (e.g., `if current_state == AppState.WAITING_FOR_PDF and update.message.document...`) and call appropriate methods on the `WorkflowManager`. `interface.py` defines the methods the rest of the app uses to interact with Telegram (e.g., `send_message(...)`, `send_photo(...)`, `pin_message(...)`).
*   **`workflow/manager.py`:** Contains the main application logic. Holds the current state. Has methods like `handle_start_command()`, `handle_pdf_input(pdf_data)`, `handle_text_evidence(text)`, `handle_finish_button()`, etc., which are called by the Telegram handlers. Orchestrates calls to `CaseManager` and `ExternalAPI`.
*   **`case/manager.py`:** Class `CaseManager`. Methods: `create_new_case()`, `process_pdf()`, `add_text_evidence()`, `add_photo_evidence()`, `add_audio_evidence()`, `update_evidence_metadata()`, `finalize_case()`, etc. Handles file I/O and JSON manipulation.
*   **`case/models.py`:** Pydantic models for `CaseInfo`, `EvidenceItem` (with subtypes for Text, Photo, Audio).
*   **`case/pdf_processor.py`:** Function or class responsible for PDF parsing (potentially using `PyPDF2` for basic text or layout info needed by the LLM).
*   **`external/`:** Simple functions wrapping `requests` calls to the LLM and Whisper APIs, handling authentication and basic error checking.

## 8. External Dependencies & Services

*   **Telegram Bot API:** Requires a Bot Token and configuration of allowed user IDs.
*   **LLM API:** Requires API Key and endpoint (e.g., Anthropic, OpenAI). Used *only* for generating summary/checklist from structured data.
*   **Whisper API (or equivalent):** Requires API Key/endpoint or local model setup. Used *only* for audio transcription.

## 9. Configuration

Environment Variables (loaded via `.env` file):

*   `TELEGRAM_BOT_TOKEN`: Your Telegram Bot token.
*   `ALLOWED_TELEGRAM_USERS`: Comma-separated string of numeric Telegram User IDs allowed to interact with the bot.
*   `LLM_API_KEY`: API Key for the chosen LLM service.
*   `LLM_API_ENDPOINT`: (Optional) Endpoint URL if not using standard SDKs.
*   `WHISPER_API_KEY`: API Key for Whisper service (if applicable).
*   `WHISPER_API_ENDPOINT`: (Optional) Endpoint for Whisper API.
*   `CASE_DATA_DIR`: Path to the directory where case data will be stored locally (defaults to `./data`).
*   `LOG_LEVEL`: Logging level (e.g., `INFO`, `DEBUG`).

## 10. Testing Strategy

*   **Test-Driven Development (TDD):** Write tests before or alongside feature implementation.
*   **Unit Tests:** Test individual functions and classes in isolation.
    *   `CaseManager` methods (mocking file system I/O).
    *   `pdf_processor` logic.
    *   State transitions within `WorkflowManager` (mocking dependencies).
    *   Pydantic model validation.
*   **Integration Tests:** Test the interaction between components.
    *   Test `WorkflowManager`'s handling of simulated Telegram events (button presses, file uploads) and ensure correct calls to `CaseManager` and `ExternalAPI` (mocked).
    *   Test the full workflow path with mocked external services.
*   **Mocking:** Use `unittest.mock` extensively to isolate components and simulate external API responses/errors and Telegram events.
*   **Continuous Testing:** Run tests frequently during development.

## 11. Future Considerations (Post-MVP)

*   **Error Handling & Recovery:** More robust handling of API failures, disk space issues, state corruption.
*   **Cloud Storage:** Re-integrate Google Drive (or other cloud storage) for backup and resilience, potentially via a simple HTTP client if not using MCP.
*   **Queries:** Implement simple query features (e.g., `/listcases`, `/getcase <id>`) accessible only in `IDLE` state.
*   **Modularity:** Refactor towards microservices and MCP if scalability or component independence becomes necessary.
*   **Flexibility:** Gradually re-introduce an LLM Agent for more flexible interactions, potentially starting with specific sub-tasks.
*   **Configuration UI:** A simple way to manage settings if needed.
*   **Security:** Enhance security beyond basic allowed user IDs if required.

## Error Handling and Robustness

This section documents the error handling and recovery mechanisms implemented in the application.

### Error Types and Recovery

The application handles various types of errors that may occur during operation:

| Error Type | Description | Recovery Mechanism |
|------------|-------------|-------------------|
| Network Errors | Connection issues with Telegram API | Automatic retries with exponential backoff |
| Timeout Errors | Operations taking too long to complete | Configurable timeouts and user notifications |
| File Errors | Issues with file uploads or corruption | Validation checks and friendly error messages |
| State Errors | Inconsistencies in application state | State recovery and reset procedures |
| API Errors | Issues with external services | Graceful degradation and fallback options |

### Error Handling Architecture

The application implements a layered approach to error handling:

1. **Function Level**: Individual functions handle expected errors and provide clear return values
2. **Module Level**: Module-specific error handling for related operations
3. **Global Level**: Application-wide error handlers for unexpected exceptions

All errors are logged with appropriate severity levels and context information.

### State Recovery Process

When errors occur, the application attempts to recover using the following process:

1. Identify the current state and the severity of the error
2. Log detailed error information for troubleshooting
3. Notify the user with a friendly error message
4. Attempt to recover the application state:
   - For minor errors, retry the operation
   - For state inconsistencies, check and repair state data
   - For unrecoverable errors, reset to a known good state (IDLE)
5. Guide the user on next steps

### Error Notification for Users

Users are provided with clear, actionable error messages that:

- Explain what went wrong in non-technical terms
- Provide guidance on what to do next
- Avoid exposing internal error details
- Maintain a positive tone

Example user-facing error messages:

- "The file is too large to process. Please try a smaller file (under 20MB)."
- "I'm having trouble connecting right now. Please check your connection and try again."
- "This PDF appears to be password-protected or corrupted. Please upload a standard PDF document."

### Timeout Handling

Large operations like file uploads are monitored for timeouts:

- PDF uploads have a configurable timeout threshold (default: 60 seconds)
- Users are notified when operations are taking longer than expected
- Progress updates are provided for long-running operations
- Asynchronous operations are properly cancelled when timeouts occur

### Network Interruption Management

The application handles network interruptions by:

- Implementing retry logic for network operations
- Using exponential backoff to avoid overwhelming the network
- Providing clear feedback when network issues are detected
- Gracefully handling reconnection when network is restored

### Case Data Integrity

To ensure case data integrity:

- All file operations use atomic write patterns (write to temp file, then rename)
- Case state is regularly validated for consistency
- Error handlers check and repair case data when possible
- Automated cleanup procedures maintain system health

### Cleanup Procedures

The application includes cleanup mechanisms to prevent resource exhaustion:

- Command-line utility to remove completed cases older than a specified age
- Automatic cleanup of temporary files after uploads
- Validation of state consistency on startup
- Recovery of incomplete or corrupted cases

### Monitoring and Alerting

Error conditions are tracked and logged to facilitate monitoring:

- Critical errors are logged with full stack traces
- Warning-level issues are logged with context information
- Error patterns can be analyzed through log aggregation
- Regular health checks validate system stability

### Testing Error Scenarios

The test suite includes specific tests for error conditions:

- Network failure simulations
- Timeout simulations
- Invalid input handling tests
- State corruption recovery tests
- File system error tests

---

This detailed document should provide a clear blueprint for developing the MVP. Remember to keep the code clean, test thoroughly, and focus on getting the core, button-driven workflow reliably functional first.