"""API package for external service integrations."""
from .whisper import WhisperAPI, TranscriptionError, TransientError, PermanentError
from .llm import LLMAPI, LLMError, TransientError as LLMTransientError, PermanentError as LLMPermanentError
from .anthropic import AnthropicAPI, AnthropicError, TransientError as AnthropicTransientError, PermanentError as AnthropicPermanentError 