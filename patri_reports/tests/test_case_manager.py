import os
import json
import pytest
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

from patri_reports.utils.config import CASE_ID_PREFIX
from patri_reports.case_manager import CaseManager
from patri_reports.models.case import CaseInfo, TextEvidence, PhotoEvidence, AudioEvidence


@pytest.fixture
def temp_data_dir():
    """Create a temporary directory for test data."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    # Clean up after tests
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def case_manager(temp_data_dir):
    """Create a CaseManager instance with a temporary data directory."""
    return CaseManager(data_dir=temp_data_dir)


def test_create_new_case(case_manager):
    """Test creating a new case with proper structure."""
    # Mock datetime to get consistent year
    current_year = datetime.now().year
    
    case_info = case_manager.create_new_case()
    
    # Check that case_info is a valid CaseInfo object with a UUID
    assert isinstance(case_info, CaseInfo)
    assert case_info.case_id is not None
    
    # Check that the directory structure was created with year directory
    case_dir = Path(case_manager.data_dir) / str(current_year) / case_info.case_id
    assert case_dir.exists()
    assert (case_dir / "photos").exists()
    assert (case_dir / "audio").exists()
    
    # Check that the case_info.json file was created
    case_info_file = case_dir / "case_info.json"
    assert case_info_file.exists()
    
    # Check that the content of the file is valid JSON and matches our case_info
    with open(case_info_file, 'r') as f:
        saved_data = json.load(f)
    assert saved_data["case_id"] == case_info.case_id


def test_load_case(case_manager):
    """Test that we can load a previously saved case."""
    # Create a new case first
    original_case = case_manager.create_new_case()
    case_id = original_case.case_id
    
    # Load the case
    loaded_case = case_manager.load_case(case_id)
    
    # Check that loaded case matches the original
    assert loaded_case.case_id == original_case.case_id
    
    # Test loading a non-existent case
    non_existent_case = case_manager.load_case("non_existent_id")
    assert non_existent_case is None


def test_save_case(case_manager):
    """Test saving case information."""
    case_info = case_manager.create_new_case()
    
    # Modify the case
    case_info.rai = "test_rai_12345"
    case_info.city = "Test City"
    case_info.case_year = 2023  # Set a specific year
    
    # Save it
    result = case_manager.save_case(case_info)
    assert result is True
    
    # Load it again and check that changes were saved
    loaded_case = case_manager.load_case(case_info.case_id, 2023)
    assert loaded_case.rai == "test_rai_12345"
    assert loaded_case.city == "Test City"


def test_save_pdf(case_manager):
    """Test saving a PDF to a case."""
    case_info = case_manager.create_new_case()
    case_id = case_info.case_id
    current_year = datetime.now().year
    
    # Create fake PDF data
    pdf_data = b"%PDF-1.5\nTest PDF content"
    
    # Save the PDF
    pdf_path = case_manager.save_pdf(case_id, pdf_data, current_year)
    assert pdf_path is not None
    
    # Check that the file exists and has correct content
    pdf_file = Path(pdf_path)
    assert pdf_file.exists()
    with open(pdf_file, 'rb') as f:
        saved_data = f.read()
    assert saved_data == pdf_data
    
    # Check that case info was updated
    updated_case = case_manager.load_case(case_id, current_year)
    assert updated_case.case_pdf_path == pdf_path
    assert updated_case.timestamps.case_received is not None


def test_add_text_evidence(case_manager):
    """Test adding text evidence to a case."""
    case_info = case_manager.create_new_case()
    case_id = case_info.case_id
    current_year = datetime.now().year
    
    # Add text evidence
    text_content = "This is a test note"
    evidence_id = case_manager.add_text_evidence(case_id, text_content, current_year)
    
    assert evidence_id is not None
    
    # Check that case was updated
    updated_case = case_manager.load_case(case_id, current_year)
    assert len(updated_case.evidence) == 1
    assert updated_case.evidence[0].type == "text"
    assert updated_case.evidence[0].content == text_content
    assert updated_case.timestamps.attendance_started is not None


def test_add_photo_evidence(case_manager):
    """Test adding photo evidence to a case."""
    case_info = case_manager.create_new_case()
    case_id = case_info.case_id
    current_year = datetime.now().year
    
    # Create fake photo data
    photo_data = b"FAKE_JPEG_DATA"
    
    # Add photo evidence
    evidence_id = case_manager.add_photo_evidence(case_id, photo_data, current_year)
    
    assert evidence_id is not None
    
    # Check that case was updated
    updated_case = case_manager.load_case(case_id, current_year)
    assert len(updated_case.evidence) == 1
    assert updated_case.evidence[0].type == "photo"
    assert updated_case.evidence[0].is_fingerprint is False
    
    # Check that the file exists
    photo_path = Path(updated_case.evidence[0].file_path)
    assert photo_path.exists()
    with open(photo_path, 'rb') as f:
        saved_data = f.read()
    assert saved_data == photo_data


def test_add_audio_evidence(case_manager):
    """Test adding audio evidence to a case."""
    case_info = case_manager.create_new_case()
    case_id = case_info.case_id
    current_year = datetime.now().year
    
    # Create fake audio data
    audio_data = b"FAKE_OGG_AUDIO_DATA"
    transcript = "This is a test transcript"
    
    # Add audio evidence
    evidence_id = case_manager.add_audio_evidence(case_id, audio_data, current_year, transcript)
    
    assert evidence_id is not None
    
    # Check that case was updated
    updated_case = case_manager.load_case(case_id, current_year)
    assert len(updated_case.evidence) == 1
    assert updated_case.evidence[0].type == "audio"
    assert updated_case.evidence[0].transcript == transcript
    
    # Check that the file exists
    audio_path = Path(updated_case.evidence[0].file_path)
    assert audio_path.exists()
    with open(audio_path, 'rb') as f:
        saved_data = f.read()
    assert saved_data == audio_data


def test_update_evidence_metadata(case_manager):
    """Test updating evidence metadata (e.g., marking a photo as fingerprint)."""
    case_info = case_manager.create_new_case()
    case_id = case_info.case_id
    current_year = datetime.now().year
    
    # Add a photo
    photo_data = b"FAKE_PHOTO_DATA"
    evidence_id = case_manager.add_photo_evidence(case_id, photo_data, current_year)
    
    # Update to mark as fingerprint
    result = case_manager.update_evidence_metadata(case_id, evidence_id, {"is_fingerprint": True}, current_year)
    assert result is True
    
    # Check that metadata was updated
    updated_case = case_manager.load_case(case_id, current_year)
    assert updated_case.evidence[0].is_fingerprint is True
    
    # Test updating non-existent evidence
    bad_result = case_manager.update_evidence_metadata(case_id, "non_existent_id", {"is_fingerprint": True}, current_year)
    assert bad_result is False


def test_finalize_case(case_manager):
    """Test finalizing a case (marking collection as finished)."""
    case_info = case_manager.create_new_case()
    case_id = case_info.case_id
    current_year = datetime.now().year
    
    # Finalize the case
    result = case_manager.finalize_case(case_id, current_year)
    assert result is True
    
    # Check that the case was properly marked as finalized
    updated_case = case_manager.load_case(case_id, current_year)
    assert updated_case.timestamps.collection_finished is not None
    
    # Test finalizing a non-existent case
    bad_result = case_manager.finalize_case("non_existent_id", current_year)
    assert bad_result is False


def test_list_cases(case_manager):
    """Test listing all cases."""
    # Clean up any existing test cases in the data directory
    import shutil
    for item in Path(case_manager.data_dir).glob('*'):
        if item.is_dir():
            shutil.rmtree(item)
    
    # Create a few cases
    case_info1 = case_manager.create_new_case()
    case_info1.case_year = 2022
    case_manager.save_case(case_info1)
    
    case_info2 = case_manager.create_new_case()
    case_info2.case_year = 2023
    case_manager.save_case(case_info2)
    
    case_info3 = case_manager.create_new_case()
    case_info3.case_year = 2023
    case_manager.save_case(case_info3)
    
    # List cases
    cases = case_manager.list_cases()
    
    # Check that we have the expected cases
    assert len(cases) >= 3  # May have other cases from previous tests
    
    # Check that case IDs are correct
    case_ids = [case["case_id"] for case in cases]
    assert case_info1.case_id in case_ids
    assert case_info2.case_id in case_ids
    assert case_info3.case_id in case_ids


@patch('patri_reports.case_manager.PdfProcessor.process_pdf')
@patch('patri_reports.case_manager.is_valid_pdf')
def test_process_pdf(mock_is_valid, mock_process, case_manager):
    """Test processing a PDF to extract case information."""
    # Mock is_valid_pdf to return True
    mock_is_valid.return_value = True
    
    # Create a sample processed case info 
    processed_case = CaseInfo()
    processed_case.case_number = 12345
    processed_case.case_year = 2023
    processed_case.report_number = 98765
    processed_case.rai = "54321"
    processed_case.requesting_unit = "Test Unit"
    
    # Mock process_pdf to return our sample case info
    mock_process.return_value = processed_case
    
    # Create fake PDF data
    pdf_data = b"%PDF-1.5\nTest PDF content"
    
    # Process the PDF
    case_info = case_manager.process_pdf(pdf_data)
    
    # Check that mocks were called correctly
    mock_is_valid.assert_called_once_with(pdf_data)
    mock_process.assert_called_once_with(pdf_data)
    
    # Check that case_info contains the expected data
    assert case_info is not None
    assert case_info.case_number == 12345
    assert case_info.case_year == 2023
    assert case_info.report_number == 98765
    assert case_info.rai == "54321"
    assert case_info.requesting_unit == "Test Unit"
    
    # Check that the case ID is formatted correctly if PDF processing succeeded
    expected_case_id = f"{CASE_ID_PREFIX}_12345_98765_2023"
    assert case_info.case_id == expected_case_id
    
    # Verify that the directory structure was created
    case_dir = Path(case_manager.data_dir) / "2023" / expected_case_id
    assert case_dir.exists()
    assert (case_dir / "photos").exists()
    assert (case_dir / "audio").exists()
    
    # Verify that the PDF was saved
    assert (case_dir / "case_pdf.pdf").exists() 