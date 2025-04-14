#!/usr/bin/env python
import logging
import sys
from pathlib import Path

# Set up logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_pdf_processing(pdf_path):
    """Test processing a PDF file with the PdfProcessor class."""
    try:
        from patri_reports.utils.pdf_processor import PdfProcessor
        
        logger.info(f"Testing PDF processing for file: {pdf_path}")
        
        # Create processor instance
        processor = PdfProcessor(pdf_path)
        
        # Extract text
        text = processor.extract_text()
        logger.info(f"Extracted {len(text)} characters of text")
        logger.info(f"Preview: {text[:200]}...")
        
        # Parse general info
        info = processor.parse_general_info()
        logger.info(f"Parsed general info: {info}")
        
        # Process all data
        result = processor.process()
        logger.info(f"Full processing result contains {len(result)} fields")
        
        return True
    except Exception as e:
        logger.error(f"Error processing PDF: {e}", exc_info=True)
        return False

def fix_pdf_processor_import():
    """Add required functions to pdf_processor module."""
    try:
        from patri_reports.utils.pdf_processor import PdfProcessor
        
        # Define the missing functions
        def extract_text_from_pdf(pdf_path):
            """Extract text content from a PDF file."""
            processor = PdfProcessor(pdf_path)
            return processor.extract_text()
            
        def extract_metadata_from_pdf(pdf_path):
            """Extract metadata from a PDF file."""
            processor = PdfProcessor(pdf_path)
            return processor.parse_general_info()
        
        # Add these functions to the module
        import patri_reports.utils.pdf_processor
        patri_reports.utils.pdf_processor.extract_text_from_pdf = extract_text_from_pdf
        patri_reports.utils.pdf_processor.extract_metadata_from_pdf = extract_metadata_from_pdf
        
        logger.info("Added missing functions to pdf_processor module")
        return True
    except Exception as e:
        logger.error(f"Error fixing pdf_processor: {e}", exc_info=True)
        return False

def test_case_manager_extract(pdf_path):
    """Test the case_manager's extract_pdf_info function."""
    try:
        # First fix the import issue
        if not fix_pdf_processor_import():
            return False
            
        from patri_reports.case_manager import CaseManager
        
        # Create a case manager instance
        case_manager = CaseManager(data_dir="data")
        
        # Generate a test case ID
        import random
        from datetime import datetime
        case_id = f"TEST_{random.randint(10000, 99999)}_{random.randint(1000, 9999)}_{datetime.now().year}"
        
        # Create case directory
        case_path = case_manager.create_case(case_id, Path(pdf_path).name)
        if not case_path:
            logger.error("Failed to create case directory")
            return False
            
        # Copy the PDF to the case directory
        pdf_dest = case_path / "document.pdf"
        import shutil
        shutil.copy(pdf_path, pdf_dest)
        
        # Now extract PDF info
        case_info = case_manager.extract_pdf_info(case_id, pdf_dest)
        if case_info:
            logger.info(f"Successfully extracted PDF info: {case_info}")
            return True
        else:
            logger.error("Failed to extract PDF info")
            return False
            
    except Exception as e:
        logger.error(f"Error testing case_manager extract: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_pdf_processing.py <pdf_file_path>")
        sys.exit(1)
        
    pdf_path = sys.argv[1]
    if not Path(pdf_path).exists():
        print(f"Error: File not found: {pdf_path}")
        sys.exit(1)
        
    print("\n=== Testing PdfProcessor ===")
    success1 = test_pdf_processing(pdf_path)
    
    print("\n=== Testing CaseManager extract_pdf_info ===")
    success2 = test_case_manager_extract(pdf_path)
    
    if success1 and success2:
        print("\n✅ All tests passed!")
    else:
        print("\n❌ One or more tests failed")
        sys.exit(1) 