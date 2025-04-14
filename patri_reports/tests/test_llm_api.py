import unittest
from unittest.mock import patch, MagicMock
import json

from patri_reports.api.llm import LLMAPI, PermanentError


class TestLLMAPI(unittest.TestCase):
    """Test the LLMAPI wrapper for OpenAI integration."""

    def setUp(self):
        """Set up test environment."""
        # Create a test API key
        self.api_key = "test_openai_api_key"
        self.api = LLMAPI(api_key=self.api_key)
        
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

    @patch('patri_reports.api.llm.requests.post')
    def test_generate_summary_success(self, mock_post):
        """Test successful summary generation."""
        # Mock successful API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "This is a test summary."
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        # Call the generate_summary method
        result = self.api.generate_summary(self.case_data)

        # Assert the result
        self.assertEqual(result, "This is a test summary.")
        
        # Verify the API was called with correct parameters
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(kwargs['headers']['Authorization'], f"Bearer {self.api_key}")
        self.assertEqual(kwargs['json']['model'], "gpt-3.5-turbo")
        
        # Check that the message contains our case data
        self.assertIn("12345/2023", kwargs['json']['messages'][1]['content'])
        self.assertIn("Test Unit", kwargs['json']['messages'][1]['content'])

    @patch('patri_reports.api.llm.requests.post')
    def test_generate_checklist_success(self, mock_post):
        """Test successful checklist generation."""
        # Mock successful API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "1. Test checklist item\n2. Another test item"
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        # Call the generate_checklist method
        result = self.api.generate_checklist(self.case_data)

        # Assert the result
        self.assertEqual(result, "1. Test checklist item\n2. Another test item")
        
        # Verify the API was called with correct parameters
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(kwargs['headers']['Authorization'], f"Bearer {self.api_key}")
        
        # Check that the message contains trace information
        self.assertIn("Fingerprint", kwargs['json']['messages'][1]['content'])
        self.assertIn("FP001", kwargs['json']['messages'][1]['content'])

    @patch('patri_reports.api.llm.requests.post')
    def test_api_error_handling(self, mock_post):
        """Test handling of API errors."""
        # Mock error response
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad request"
        mock_post.return_value = mock_response

        # Call the generate_summary method
        result = self.api.generate_summary(self.case_data)

        # Assert the result is None (indicating failure)
        self.assertIsNone(result)
        
        # Verify the API was called once
        mock_post.assert_called_once()

    @patch('patri_reports.api.llm.requests.post')
    def test_retry_on_transient_error(self, mock_post):
        """Test retry behavior on transient errors."""
        # Setup mock responses: first with 429 error, then success
        error_response = MagicMock()
        error_response.status_code = 429
        error_response.text = "Rate limit exceeded"
        
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "Successful after retry"
                    }
                }
            ]
        }
        
        # Configure mock to return the error response first, then the success response
        mock_post.side_effect = [error_response, success_response]

        # Call the generate_summary method with small backoff for faster test
        result = self.api.generate_summary(self.case_data, initial_backoff=0.01)

        # Assert the result
        self.assertEqual(result, "Successful after retry")
        
        # Verify the API was called twice
        self.assertEqual(mock_post.call_count, 2)

    def test_missing_api_key(self):
        """Test error handling for missing API key."""
        # Create an API instance without an API key
        api = LLMAPI(api_key=None)
        
        # Call the generate_summary method - it should return None
        result = api.generate_summary(self.case_data)
        self.assertIsNone(result, "Expected None result when API key is missing")


if __name__ == '__main__':
    unittest.main() 