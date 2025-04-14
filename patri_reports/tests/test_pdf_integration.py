import json
import os
from pathlib import Path
import pytest

# Import the module being tested
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from patri_reports.utils.pdf_processor import PdfProcessor
from patri_reports.models.case import CaseInfo


class TestPdfIntegration:
    """Integration tests for the PDF processor using real PDF files."""
    
    def setup_method(self):
        """Set up test environment before each test."""
        # Use the current file's directory to locate test files
        current_dir = Path(__file__).parent
        self.test_files_dir = current_dir / "files"
        self.pdf1_path = self.test_files_dir / "request1.pdf"
        self.pdf2_path = self.test_files_dir / "request2.pdf"
        self.expected1_path = self.test_files_dir / "request1_expected.json"
        self.expected2_path = self.test_files_dir / "request2_expected.json"
        
        # Make sure all test files exist
        assert self.pdf1_path.exists(), f"Test file {self.pdf1_path} not found"
        assert self.pdf2_path.exists(), f"Test file {self.pdf2_path} not found"
        assert self.expected1_path.exists(), f"Expected file {self.expected1_path} not found"
        assert self.expected2_path.exists(), f"Expected file {self.expected2_path} not found"
    
    def load_expected_json(self, file_path):
        """Load the expected JSON data from a file."""
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def compare_outputs(self, case_info: CaseInfo, expected_data: dict):
        """Compare the case_info object with the expected data."""
        # Basic information
        assert case_info.case_number == expected_data['case_number']
        assert case_info.case_year == expected_data['case_year']
        assert case_info.report_number == expected_data['report_number']
        assert case_info.rai == expected_data['rai']
        assert case_info.requesting_unit == expected_data['requesting_unit']
        assert case_info.authority == expected_data['authority']
        assert case_info.city == expected_data['city']
        assert case_info.address == expected_data['address']
        assert case_info.address_complement == expected_data['address_complement']
        
        # Coordinates should be a tuple of two floats
        if expected_data['coordinates']:
            assert len(case_info.coordinates) == 2
            assert isinstance(case_info.coordinates[0], float)
            assert isinstance(case_info.coordinates[1], float)
            assert case_info.coordinates[0] == pytest.approx(expected_data['coordinates'][0])
            assert case_info.coordinates[1] == pytest.approx(expected_data['coordinates'][1])
        else:
            assert case_info.coordinates is None
        
        # Lists
        assert len(case_info.history) == len(expected_data['history'])
        for i, history_item in enumerate(case_info.history):
            expected_history = expected_data['history'][i]
            assert history_item.title == expected_history['title']
            assert history_item.content == expected_history['content']
        
        assert len(case_info.linked_requests) == len(expected_data['linked_requests'])
        for i, request in enumerate(case_info.linked_requests):
            expected_request = expected_data['linked_requests'][i]
            assert request.request_number == expected_request['request_number']
            assert request.creation_date == expected_request['creation_date']
            assert request.responsible == expected_request['responsible']
            assert request.origin_unit == expected_request['origin_unit']
            assert request.affected_unit == expected_request['affected_unit']
            assert request.content == expected_request['content']
        
        assert len(case_info.involved_team) == len(expected_data['involved_team'])
        for i, team_member in enumerate(case_info.involved_team):
            expected_member = expected_data['involved_team'][i]
            assert team_member.name == expected_member['name']
            assert team_member.role == expected_member['role']
        
        assert len(case_info.traces) == len(expected_data['traces'])
        for i, trace in enumerate(case_info.traces):
            expected_trace = expected_data['traces'][i]
            assert trace.type == expected_trace['type']
            assert trace.id == expected_trace['id']
            assert trace.examinations == expected_trace['examinations']
            assert trace.status == expected_trace['status']
        
        assert len(case_info.involved_people) == len(expected_data['involved_people'])
        for i, person in enumerate(case_info.involved_people):
            expected_person = expected_data['involved_people'][i]
            assert person.name == expected_person['name']
            assert person.involvement == expected_person['involvement']
            assert person.cpf == expected_person['cpf']
    
    def test_pdf_processor_request1(self):
        """Test processing request1.pdf and compare with expected result."""
        # Load the expected data
        expected_data = self.load_expected_json(self.expected1_path)
        
        # Process the PDF
        case_info = PdfProcessor.process_pdf(self.pdf1_path)
        
        # Verify it returned something
        assert case_info is not None
        
        # Compare the result with expected data
        self.compare_outputs(case_info, expected_data)
    
    def test_pdf_processor_request2(self):
        """Test processing request2.pdf and compare with expected result."""
        # Load the expected data
        expected_data = self.load_expected_json(self.expected2_path)
        
        # Process the PDF
        case_info = PdfProcessor.process_pdf(self.pdf2_path)
        
        # Verify it returned something
        assert case_info is not None
        
        # Compare the result with expected data
        self.compare_outputs(case_info, expected_data) 