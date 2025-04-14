import unittest
from unittest.mock import patch, MagicMock
import json
import os

from patri_reports.api.anthropic import AnthropicAPI, PermanentError


class TestAnthropicAPI(unittest.TestCase):
    """Test the AnthropicAPI wrapper for Claude integration."""

    def setUp(self):
        """Set up test environment."""
        # Create a test API key
        self.api_key = "test_anthropic_api_key"
        self.api = AnthropicAPI(api_key=self.api_key)
        
        # Sample case data for testing
        self.case_data = {
            "case_number": 12345,
            "case_year": 2023,
            "requesting_unit": "Test Unit",
            "address": "123 Test Street",
            "history": [
                {"title": "Incident", "content": "This is a test incident."}
            ],
            "evidence": [
                {"type": "note", "content": "Test note content"}
            ],
            "traces": [
                {"type": "Fingerprint", "id": "FP001", "examinations": "Standard analysis"}
            ]
        }

    @patch('patri_reports.api.anthropic.requests.post')
    def test_generate_summary_success(self, mock_post):
        """Test successful summary generation."""
        # Mock successful API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": "This is a test summary from Claude."
                }
            ]
        }
        mock_post.return_value = mock_response

        # Call the generate_summary method
        result = self.api.generate_summary(self.case_data)

        # Assert the result
        self.assertEqual(result, "This is a test summary from Claude.")
        
        # Verify the API was called with correct parameters
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(kwargs['headers']['x-api-key'], self.api_key)
        
        # We don't check the exact model name anymore as it can come from environment variables
        # Just verify that it's a string and present
        self.assertIsInstance(kwargs['json']['model'], str)
        self.assertTrue(kwargs['json']['model'])  # Not empty
        
        # Check that the message contains our case data
        self.assertIn("12345/2023", kwargs['json']['messages'][0]['content'])
        self.assertIn("Test Unit", kwargs['json']['messages'][0]['content'])

    @patch('patri_reports.api.anthropic.requests.post')
    def test_generate_checklist_success(self, mock_post):
        """Test successful checklist generation."""
        # Mock successful API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": "1. Claude test checklist item\n2. Another Claude test item"
                }
            ]
        }
        mock_post.return_value = mock_response

        # Call the generate_checklist method
        result = self.api.generate_checklist(self.case_data)

        # Assert the result
        self.assertEqual(result, "1. Claude test checklist item\n2. Another Claude test item")
        
        # Verify the API was called with correct parameters
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(kwargs['headers']['x-api-key'], self.api_key)
        
        # Check that the message contains trace information
        self.assertIn("Fingerprint", kwargs['json']['messages'][0]['content'])
        self.assertIn("FP001", kwargs['json']['messages'][0]['content'])

    @patch('patri_reports.api.anthropic.requests.post')
    def test_api_error_handling(self, mock_post):
        """Test handling of API errors."""
        # Mock error response
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad request"
        mock_post.return_value = mock_response

        # Call the generate_summary method - should raise PermanentError
        with self.assertRaises(PermanentError):
            self.api.generate_summary(self.case_data)

    @patch('patri_reports.api.anthropic.requests.post')
    def test_retry_on_transient_error(self, mock_post):
        """Test retry behavior on transient errors."""
        # Setup mock responses: first with 429 error, then success
        error_response = MagicMock()
        error_response.status_code = 429
        error_response.text = "Rate limit exceeded"
        
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": "Successful after retry with Claude"
                }
            ]
        }
        
        # Configure mock to return the error response first, then the success response
        mock_post.side_effect = [error_response, success_response]

        # Call the generate_summary method with small backoff for faster test
        result = self.api.generate_summary(self.case_data, initial_backoff=0.01)

        # Assert the result
        self.assertEqual(result, "Successful after retry with Claude")
        
        # Verify the API was called twice
        self.assertEqual(mock_post.call_count, 2)

    @patch('patri_reports.api.anthropic.requests.post')
    def test_handle_missing_text_content(self, mock_post):
        """Test handling of response with missing text content."""
        # Mock response with non-text content
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [
                {
                    "type": "image",  # Not a text type
                    "source": "some_image_data"
                }
            ]
        }
        mock_post.return_value = mock_response

        # Call the generate_summary method
        with self.assertRaises(PermanentError):
            self.api.generate_summary(self.case_data)
        
        # Verify the API was called once
        mock_post.assert_called_once()

    def test_missing_api_key(self):
        """Test error handling for missing API key."""
        # Save the original env var
        original_api_key = os.environ.get("ANTHROPIC_API_KEY")
        
        try:
            # Temporarily remove the API key from environment
            if "ANTHROPIC_API_KEY" in os.environ:
                del os.environ["ANTHROPIC_API_KEY"]
            
            # Create an API instance without an API key
            api = AnthropicAPI(api_key=None)
            
            # Call the generate_summary method and expect a PermanentError
            with self.assertRaises(PermanentError):
                api.generate_summary(self.case_data)
        finally:
            # Restore the original env var
            if original_api_key:
                os.environ["ANTHROPIC_API_KEY"] = original_api_key


if __name__ == '__main__':
    unittest.main() 