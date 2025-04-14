import pytest
import os
import tempfile
from unittest.mock import patch, MagicMock
from pathlib import Path

from patri_reports.api.whisper import (
    WhisperAPI, 
    TransientError, 
    PermanentError
)

# Skip tests if no API key is available
skip_if_no_api_key = pytest.mark.skipif(
    os.environ.get("OPENAI_API_KEY") is None,
    reason="OpenAI API key not found in environment variables"
)

class TestWhisperAPI:
    """Test the WhisperAPI wrapper for audio transcription."""
    
    def setup_method(self):
        """Set up test environment before each test."""
        # Create a test API key
        self.api_key = "test_api_key"
        self.api = WhisperAPI(api_key=self.api_key)
        
        # Create a temporary audio file for testing
        self.temp_audio_file = tempfile.NamedTemporaryFile(delete=False, suffix=".ogg")
        self.temp_audio_file.write(b"fake audio data")
        self.temp_audio_file.close()
    
    def teardown_method(self):
        """Clean up after tests."""
        # Remove the temporary audio file
        if os.path.exists(self.temp_audio_file.name):
            os.unlink(self.temp_audio_file.name)
    
    def test_init_with_defaults(self):
        """Test initializing WhisperAPI with default values."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test_key"}):
            api = WhisperAPI()
            assert api.api_key == "test_key"
            assert api.base_url == "https://api.openai.com/v1/audio/transcriptions"
    
    def test_init_with_custom_values(self):
        """Test initializing WhisperAPI with custom values."""
        api = WhisperAPI(api_key="custom_key", base_url="https://custom.api.url")
        assert api.api_key == "custom_key"
        assert api.base_url == "https://custom.api.url"
    
    def test_transcribe_missing_api_key(self):
        """Test transcription fails with missing API key."""
        with patch.dict(os.environ, {}, clear=True):
            api = WhisperAPI()
            with pytest.raises(PermanentError) as exc_info:
                api.transcribe("dummy_path")
            assert "API key not configured" in str(exc_info.value)
    
    def test_transcribe_file_not_found(self):
        """Test transcription fails when file not found."""
        api = WhisperAPI(api_key="test_key")
        with pytest.raises(PermanentError) as exc_info:
            api.transcribe("/nonexistent/path/file.ogg")
        assert "Audio file not found" in str(exc_info.value)
    
    def test_transcribe_handles_transient_error(self):
        """Test transcription handles transient errors with retry logic."""
        # Create a temp file to pass file existence check
        with tempfile.NamedTemporaryFile(suffix='.ogg') as temp_file:
            api = WhisperAPI(api_key="test_key")
            
            # Mock the API request to raise a transient error and then succeed
            with patch.object(api, '_make_transcription_request') as mock_request:
                mock_request.side_effect = [
                    TransientError("Rate limit exceeded"),
                    "This is the transcription result"
                ]
                
                # Call the method with a small initial backoff
                result = api.transcribe(temp_file.name, initial_backoff=0.01)
                
                # Verify the result and that the method was called twice
                assert result == "This is the transcription result"
                assert mock_request.call_count == 2
    
    def test_transcribe_max_retries_exceeded(self):
        """Test transcription fails after max retries for transient errors."""
        # Create a temp file to pass file existence check
        with tempfile.NamedTemporaryFile(suffix='.ogg') as temp_file:
            api = WhisperAPI(api_key="test_key")
            
            # Mock the API request to always raise a transient error
            with patch.object(api, '_make_transcription_request') as mock_request:
                mock_request.side_effect = TransientError("Rate limit exceeded")
                
                # Call the method with a small initial backoff and only 2 retries
                result = api.transcribe(temp_file.name, max_retries=2, initial_backoff=0.01)
                
                # Verify the result is None and the method was called the expected times
                assert result is None
                assert mock_request.call_count == 3  # Initial + 2 retries
    
    def test_transcribe_permanent_error_no_retry(self):
        """Test transcription doesn't retry permanent errors."""
        # Create a temp file to pass file existence check
        with tempfile.NamedTemporaryFile(suffix='.ogg') as temp_file:
            api = WhisperAPI(api_key="test_key")
            
            # Mock the API request to raise a permanent error
            with patch.object(api, '_make_transcription_request') as mock_request:
                mock_request.side_effect = PermanentError("Invalid audio format")
                
                # Call the method with multiple retries
                result = api.transcribe(temp_file.name, max_retries=3)
                
                # Verify the result is None and the method was called only once
                assert result is None
                assert mock_request.call_count == 1
    
    @patch('requests.post')
    def test_make_transcription_request_success(self, mock_post):
        """Test successful transcription request."""
        # Create a mock response with successful data
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"text": "This is the transcription"}
        mock_post.return_value = mock_response
        
        # Create a temp file to use in the test
        with tempfile.NamedTemporaryFile(suffix='.ogg') as temp_file:
            api = WhisperAPI(api_key="test_key")
            result = api._make_transcription_request(temp_file.name)
            
            # Verify the result
            assert result == "This is the transcription"
            mock_post.assert_called_once()
    
    @patch('requests.post')
    def test_make_transcription_request_transient_error(self, mock_post):
        """Test handling of transient API errors."""
        # Create a mock response with rate limit error
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limit exceeded"
        mock_post.return_value = mock_response
        
        # Create a temp file to use in the test
        with tempfile.NamedTemporaryFile(suffix='.ogg') as temp_file:
            api = WhisperAPI(api_key="test_key")
            
            with pytest.raises(TransientError) as exc_info:
                api._make_transcription_request(temp_file.name)
            
            assert "API returned status 429" in str(exc_info.value)
            mock_post.assert_called_once()
    
    @patch('requests.post')
    def test_make_transcription_request_permanent_error(self, mock_post):
        """Test handling of permanent API errors."""
        # Create a mock response with validation error
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad request: invalid audio format"
        mock_post.return_value = mock_response
        
        # Create a temp file to use in the test
        with tempfile.NamedTemporaryFile(suffix='.ogg') as temp_file:
            api = WhisperAPI(api_key="test_key")
            
            with pytest.raises(PermanentError) as exc_info:
                api._make_transcription_request(temp_file.name)
            
            assert "API returned status 400" in str(exc_info.value)
            mock_post.assert_called_once()
    
    # Additional test consolidated from unittest version
    @patch('patri_reports.api.whisper.requests.post')
    def test_transcribe_full_request_flow(self, mock_post):
        """Test the complete transcription flow including request parameters."""
        # Mock successful API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"text": "This is a test transcription."}
        mock_post.return_value = mock_response

        # Call the transcribe method with the actual temp file
        result = self.api.transcribe(self.temp_audio_file.name)

        # Assert the result
        assert result == "This is a test transcription."
        
        # Verify the API was called with correct parameters
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs['headers']['Authorization'] == f"Bearer {self.api_key}"
        assert kwargs['data']['model'] == "whisper-1"
        assert 'file' in kwargs['files'] 