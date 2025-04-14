import pytest
from unittest.mock import MagicMock, patch

from patri_reports.utils.pdf_processor import is_valid_pdf


class TestPdfProcessor:
    """Tests for the PDF processor module."""
    
    def test_is_valid_pdf_with_valid_data(self):
        """Test PDF validation with valid data."""
        # Mock a simple valid PDF data
        mock_pdf_data = b'%PDF-1.4\n...<some pdf content>...'
        
        with patch('patri_reports.utils.pdf_processor.PdfReader') as mock_reader:
            # Configure the mock to simulate a valid PDF with at least one page
            mock_reader.return_value.pages = [MagicMock()]
            
            # Test the function
            assert is_valid_pdf(mock_pdf_data) is True
    
    def test_is_valid_pdf_with_invalid_data(self):
        """Test PDF validation with invalid data."""
        # Invalid PDF data (no PDF header)
        invalid_pdf_data = b'This is not a PDF file'
        
        assert is_valid_pdf(invalid_pdf_data) is False
    
    def test_is_valid_pdf_with_exception(self):
        """Test PDF validation handling exceptions."""
        mock_pdf_data = b'%PDF-1.4\n...<some pdf content>...'
        
        with patch('patri_reports.utils.pdf_processor.PdfReader') as mock_reader:
            # Configure the mock to raise an exception during parsing
            mock_reader.side_effect = Exception("PDF parsing error")
            
            # Test the function
            assert is_valid_pdf(mock_pdf_data) is False 