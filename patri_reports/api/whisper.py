import os
import time
import logging
import requests
from typing import Optional, Dict, Any
from pathlib import Path

# Configure logging
logger = logging.getLogger(__name__)

class TranscriptionError(Exception):
    """Base exception for transcription errors."""
    pass

class TransientError(TranscriptionError):
    """Temporary error that may be resolved by retrying."""
    pass

class PermanentError(TranscriptionError):
    """Permanent error that will not be resolved by retrying."""
    pass

class WhisperAPI:
    """Wrapper for OpenAI's Whisper API for audio transcription."""
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, use_dummy_responses: bool = False):
        """Initialize the WhisperAPI client.
        
        Args:
            api_key: OpenAI API key. If None, uses OPENAI_API_KEY from environment.
            base_url: API base URL. If None, uses the default OpenAI API URL.
            use_dummy_responses: If True, returns dummy transcriptions instead of calling the API.
        """
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.use_dummy_responses = use_dummy_responses
        
        if use_dummy_responses:
            logger.info("WhisperAPI initialized in dummy response mode")
        elif not self.api_key:
            logger.warning("No API key provided for WhisperAPI. Transcription will fail.")
        
        self.base_url = base_url or "https://api.openai.com/v1/audio/transcriptions"
    
    def transcribe(self, 
                   audio_file_path: str, 
                   max_retries: int = 3, 
                   initial_backoff: float = 1.0,
                   language: Optional[str] = None) -> Optional[str]:
        """Transcribe an audio file using OpenAI's Whisper API.
        
        Args:
            audio_file_path: Path to the audio file.
            max_retries: Maximum number of retry attempts.
            initial_backoff: Initial backoff time in seconds.
            language: Optional language code (e.g., 'pt' for Portuguese).
            
        Returns:
            Transcribed text if successful, None otherwise.
            
        Raises:
            TransientError: For temporary errors that may be resolved by retrying.
            PermanentError: For permanent errors that will not be resolved by retrying.
        """
        # Return dummy response if enabled
        if self.use_dummy_responses:
            logger.info(f"Using dummy transcription for audio file: {audio_file_path}")
            
            # Simple dummy responses based on language
            if language == "pt":
                return "Texto simulado para transcrição"
            else:
                return "Dummy text for transcription"
        
        # Check API key and file existence for real API calls
        if not self.api_key:
            raise PermanentError("API key not configured for Whisper API")
        
        if not Path(audio_file_path).exists():
            raise PermanentError(f"Audio file not found: {audio_file_path}")
        
        retries = 0
        while retries <= max_retries:
            try:
                return self._make_transcription_request(audio_file_path, language)
            except TransientError as e:
                retries += 1
                wait_time = initial_backoff * (2 ** (retries - 1))  # Exponential backoff
                logger.warning(f"Transient error on transcription attempt {retries}/{max_retries}: {e}. Retrying in {wait_time}s")
                
                if retries <= max_retries:
                    time.sleep(wait_time)
                else:
                    logger.error(f"Maximum retries ({max_retries}) reached for audio transcription")
                    break
            except PermanentError as e:
                logger.error(f"Permanent error during transcription: {e}")
                break
            except Exception as e:
                logger.exception(f"Unexpected error during transcription: {e}")
                break
        
        return None
    
    def _make_transcription_request(self, audio_file_path: str, language: Optional[str] = None) -> str:
        """Make the actual API request to the Whisper service.
        
        Args:
            audio_file_path: Path to the audio file.
            language: Optional language code.
            
        Returns:
            Transcribed text.
            
        Raises:
            TransientError: For temporary errors that may be resolved by retrying.
            PermanentError: For permanent errors that will not be resolved by retrying.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "model": "whisper-1"
        }
        
        if language:
            payload["language"] = language
        
        try:
            with open(audio_file_path, "rb") as audio_file:
                files = {
                    "file": (Path(audio_file_path).name, audio_file, "audio/mpeg")
                }
                
                logger.debug(f"Sending transcription request for {audio_file_path}")
                response = requests.post(
                    self.base_url,
                    headers=headers,
                    data=payload,
                    files=files,
                    timeout=60  # Longer timeout for audio processing
                )
            
            # Handle response status codes
            if response.status_code == 200:
                result = response.json()
                if "text" in result:
                    logger.info(f"Successfully transcribed audio file: {audio_file_path}")
                    return result["text"]
                else:
                    raise PermanentError(f"Missing 'text' in API response: {result}")
            elif response.status_code in (429, 500, 502, 503, 504):
                # Rate limiting or server errors - these are transient
                raise TransientError(f"API returned status {response.status_code}: {response.text}")
            else:
                # Client errors and other issues - these are permanent
                raise PermanentError(f"API returned status {response.status_code}: {response.text}")
                
        except requests.RequestException as e:
            # Network errors - these are transient
            raise TransientError(f"Network error during API request: {e}")
        except IOError as e:
            # File errors - these are permanent
            raise PermanentError(f"File error when reading audio file: {e}") 