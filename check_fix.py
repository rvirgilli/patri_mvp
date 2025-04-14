#!/usr/bin/env python
import logging
import sys
from pathlib import Path
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_pdf_extraction(pdf_path):
    """Test the PDF extraction with our fixed code."""
    try:
        from patri_reports.case_manager import CaseManager
        
        # Create a case manager instance
        case_manager = CaseManager(data_dir="data")
        
        # Generate a test case ID
        import random
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
        
        # Now extract PDF info using our fixed method
        logger.info(f"Extracting PDF info for case {case_id}...")
        case_info = case_manager.extract_pdf_info(case_id, pdf_dest)
        
        if not case_info:
            logger.error("Failed to extract PDF info")
            return False
        
        # Print the extracted data to verify
        logger.info("=== Extracted PDF Info ===")
        logger.info(f"Case ID: {case_info.case_id}")
        logger.info(f"Case Number: {case_info.case_number}")
        logger.info(f"Case Year: {case_info.case_year}")
        logger.info(f"Report Number: {case_info.report_number}")
        logger.info(f"RAI: {case_info.rai}")
        logger.info(f"Requesting Unit: {case_info.requesting_unit}")
        logger.info(f"Authority: {case_info.authority}")
        logger.info(f"City: {case_info.city}")
        logger.info(f"Address: {case_info.address}")
        logger.info(f"Coordinates: {case_info.coordinates}")
        logger.info(f"History Items: {len(case_info.history)}")
        logger.info(f"Linked Requests: {len(case_info.linked_requests)}")
        logger.info(f"Team Members: {len(case_info.involved_team)}")
        logger.info(f"Traces: {len(case_info.traces)}")
        logger.info(f"Involved People: {len(case_info.involved_people)}")
        
        # Check if important fields were extracted
        success = (
            case_info.case_number is not None and 
            case_info.case_year is not None and
            case_info.rai is not None
        )
        
        if success:
            logger.info("✅ PDF extraction successful with correct data!")
        else:
            logger.error("❌ PDF extraction failed to populate important fields")
            
        return success
            
    except Exception as e:
        logger.error(f"Error testing PDF extraction: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python check_fix.py <pdf_file_path>")
        sys.exit(1)
        
    pdf_path = sys.argv[1]
    if not Path(pdf_path).exists():
        print(f"Error: File not found: {pdf_path}")
        sys.exit(1)
        
    if test_pdf_extraction(pdf_path):
        sys.exit(0)
    else:
        sys.exit(1) 