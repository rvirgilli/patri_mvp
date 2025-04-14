import sys
import os
import logging
import unittest
from unittest.mock import patch, MagicMock
import io

# Ensure the package is in the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from patri_reports.utils import setup_logging, get_logger

class TestLogSetup(unittest.TestCase):
    """Tests for the log_setup module."""
    
    def setUp(self):
        # Clear any existing handlers before each test
        logging.root.handlers = []
    
    def test_setup_logging_default(self):
        """Test setup_logging with default parameters."""
        with patch.object(logging, 'basicConfig') as mock_config:
            root_logger = setup_logging()
            
            # Verify logging.basicConfig was called once
            mock_config.assert_called_once()
            
            # Verify it used the default parameters
            args, kwargs = mock_config.call_args
            self.assertEqual(kwargs['level'], logging.INFO)  # Default level
            self.assertTrue(any(isinstance(h, logging.StreamHandler) for h in kwargs['handlers']))
            
            # Verify it returned the root logger
            self.assertEqual(root_logger, logging.getLogger())
    
    def test_setup_logging_custom_level(self):
        """Test setup_logging with custom log level."""
        with patch.object(logging, 'basicConfig') as mock_config:
            setup_logging(log_level_name="DEBUG")
            
            # Verify it used our custom level
            args, kwargs = mock_config.call_args
            self.assertEqual(kwargs['level'], logging.DEBUG)
    
    def test_setup_logging_with_file(self):
        """Test setup_logging with file output."""
        with patch.object(logging, 'basicConfig') as mock_config, \
             patch('os.makedirs') as mock_makedirs, \
             patch('os.path.exists', return_value=False), \
             patch('logging.FileHandler') as mock_file_handler:
            
            # Configure with a log file
            setup_logging(log_file="/tmp/test.log")
            
            # Verify the directory was created
            mock_makedirs.assert_called_once_with('/tmp', exist_ok=True)
            
            # Verify FileHandler was created
            mock_file_handler.assert_called_once_with('/tmp/test.log')
            
            # Verify both handlers were used
            args, kwargs = mock_config.call_args
            self.assertEqual(len(kwargs['handlers']), 2)
    
    def test_get_logger(self):
        """Test get_logger function."""
        with patch('patri_reports.utils.log_setup.setup_logging') as mock_setup:
            # Should call setup_logging if no handlers exist
            logging.root.handlers = []
            logger = get_logger("test_module")
            mock_setup.assert_called_once()
            self.assertEqual(logger.name, "test_module")
            
            # Should not call setup_logging again if handlers exist
            mock_setup.reset_mock()
            logging.root.handlers = [logging.StreamHandler()]
            logger = get_logger("another_module")
            mock_setup.assert_not_called()
            self.assertEqual(logger.name, "another_module")
    
    def test_logging_output(self):
        """Test actual logging output."""
        # Capture stdout
        captured_output = io.StringIO()
        handler = logging.StreamHandler(captured_output)
        
        # Set formatter to include logger name
        formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        
        # Configure root logger with our captured handler
        logging.root.handlers = [handler]
        logging.root.setLevel(logging.INFO)
        
        # Get a test logger and log a message
        logger = get_logger("test_output")
        logger.info("Test message")
        
        # Verify message was logged
        output = captured_output.getvalue()
        self.assertIn("test_output", output)
        self.assertIn("Test message", output)
        self.assertIn("INFO", output)

if __name__ == '__main__':
    unittest.main() 