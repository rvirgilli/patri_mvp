import re
import io
import logging
from typing import Union, Optional, Dict, Any, List, Tuple
from pathlib import Path

from pypdf import PdfReader

from ..models.case import (
    CaseInfo, HistoryItem, LinkedRequest, 
    TeamMember, Trace, InvolvedPerson
)

logger = logging.getLogger(__name__)

class PdfProcessor:
    """
    PDF Processor tool to extract and process case information from PDF files.
    
    Features:
    - Extracts raw text from a PDF and cleans formatting.
    - Parses general case information including case numbers, years, report numbers, and other details.
    - Extracts history, linked requests, team members, evidence traces, and involved people.
    
    Use the `process` method for a comprehensive extraction of all data.
    """

    def __init__(self, pdf_source: Union[str, bytes, Path]):
        # Support both bytes and path objects
        if isinstance(pdf_source, (bytes, bytearray)):
            self.reader = PdfReader(io.BytesIO(pdf_source))
        else:
            self.reader = PdfReader(pdf_source)
            
        self.text = self.extract_text()

    def extract_text(self) -> str:
        """
        Extract text from PDF, merging page texts and removing extra newlines.
        """
        text = "\n".join(
            page.extract_text() 
            for page in self.reader.pages 
            if page.extract_text()
        )
        return re.sub(r'\n{2,}', '\n', text)  # Remove multiple consecutive newlines

    def parse_general_info(self) -> Dict[str, Any]:
        """
        Extract and return general case information.
        """
        text = self.text
        title_match = re.search(r'(SEPPATRI|HOMICIDIOS)\s+(\d+)/(\d{4})\s+RG\s+(\d+)/(\d{4})', text)
        authority_match = re.search(
            r'Autoridade:\s*(.*?)\s*(?=Tipificações:|Cidade:|Endereço:)',
            text,
            re.DOTALL
        )
        address_match = re.search(
            r'Endereço:\s*(.*?)\s*(?=Complemento:|$)',
            text,
            re.DOTALL
        )
        complement_match = re.search(
            r'Complemento:\s*(.*?)\s*(?=Coordenadas:|$)',
            text,
            re.DOTALL
        )
        coordinates_match = re.search(
            r'Latitude:\s*(-?\d+,\d+).*Longitude:\s*(-?\d+,\d+)',
            text
        )

        coordinates = None
        if coordinates_match:
            lat = float(coordinates_match.group(1).replace(',', '.'))
            lon = float(coordinates_match.group(2).replace(',', '.'))
            coordinates = (lat, lon)

        return {
            'case_number': int(title_match.group(2)) if title_match else None,
            'case_year': int(title_match.group(3)) if title_match else None,
            'report_number': int(title_match.group(4)) if title_match else None,
            'rai': re.search(r'RAI:\s*(\d+)', text).group(1) if re.search(r'RAI:\s*(\d+)', text) else None,
            'requesting_unit': re.search(r'Unidade\s+Solicitante:\s*([^\n]+)', text).group(1).strip() if re.search(r'Unidade\s+Solicitante:', text) else None,
            'authority': authority_match.group(1).strip() if authority_match and authority_match.group(1).strip() else None,
            'city': re.search(r'Cidade:\s*([^\n]+)', text).group(1).strip() if re.search(r'Cidade:', text) else None,
            'address': address_match.group(1).strip() if address_match and address_match.group(1).strip() else None,
            'address_complement': complement_match.group(1).strip() if complement_match and complement_match.group(1).strip() else None,
            'coordinates': coordinates
        }

    def parse_history(self) -> List[Dict[str, str]]:
        """
        Extract and return the history as a list of dictionaries with 'title' and 'content'.
        """
        text = self.text
        history = []
        history_section = re.search(
            r'Histórico incluído em:[^\n]*\n([\s\S]*?)(?=\n\s*Requisições vinculadas|$)',
            text
        )
        if history_section:
            section_text = history_section.group(1).strip()
            pattern = re.compile(
                r'^(\S.*?):\s*([\s\S]*?)(?=^\S.*?:|\Z)',
                re.MULTILINE
            )
            for match in pattern.finditer(section_text):
                title = match.group(1).strip()
                content = match.group(2).strip()
                # Normalize whitespace within the content.
                content = re.sub(r'\s+', ' ', content)
                history.append({
                    'title': title,
                    'content': content
                })
        return history

    def parse_requests(self) -> List[Dict[str, str]]:
        """
        Extract and return linked requests.
        """
        text = self.text
        requests = []
        pattern = re.compile(
            r'Requisição\s*n[º°o]+:\s*(\d+)[\s\S]*?'
            r'Data de criação:\s*([\d/ :]+)[\s\S]*?'
            r'Respons[aá]vel:\s*([^\n]+)[\s\S]*?'
            r'Unidade de origem:\s*([^\n]+)[\s\S]*?'
            r'Unidade afeta:\s*([^\n]+)[\s\S]*?'
            r'Conte[uú]do:\s*([\s\S]+?)(?=\n\s*Equipe\b|\Z)',
            re.MULTILINE
        )
        for match in pattern.finditer(text):
            requests.append({
                'request_number': match.group(1),
                'creation_date': match.group(2).strip(),
                'responsible': match.group(3).strip(),
                'origin_unit': match.group(4).strip(),
                'affected_unit': match.group(5).strip(),
                'content': re.sub(r'\s+', ' ', match.group(6)).strip()
            })
        return requests

    def parse_team(self) -> List[Dict[str, str]]:
        """
        Extract and return the involved team members.
        """
        text = self.text
        team = []
        match = re.search(r'Equipe Envolvida\s*([\s\S]*?)(?=\n\s*Pessoas|\n\s*Vest)', text)
        if match:
            for line in match.group(1).split('\n'):
                member = re.match(r'(.+?)\s*\((.*?)\)', line.strip())
                if member:
                    team.append({
                        'name': member.group(1).strip(),
                        'role': member.group(2).strip()
                    })
        return team

    def parse_traces(self) -> List[Dict[str, str]]:
        """
        Extract and return evidence traces.
        """
        text = self.text
        traces = []
        pattern = re.compile(
            r'(\w+)\s*-\s*\d+\s*und\s*\(ID:\s*(\d+)\)[\s\S]*?'
            r'Exames:\s*([^\n]+?)\s*-\s*Status:\s*([^\n]+)',
            re.MULTILINE
        )
        for match in pattern.finditer(text):
            traces.append({
                'type': match.group(1),
                'id': match.group(2),
                'examinations': match.group(3).strip(),
                'status': match.group(4).strip()
            })
        return traces

    def parse_people(self) -> List[Dict[str, str]]:
        """
        Extract and return the involved people.
        """
        text = self.text
        people = []
        match = re.search(r'Pessoas\s*([\s\S]*?)(?=\n\s*Vest|\n\s*Powered)', text)
        if match:
            for line in match.group(1).split('\n'):
                person = re.match(r'(.+?)\s*\((.*?)\)[^CPF]*CPF:\s*(\d+)', line.strip())
                if person:
                    people.append({
                        'name': person.group(1).strip(),
                        'involvement': person.group(2).strip(),
                        'cpf': person.group(3).strip()
                    })
        return people

    def process(self) -> Dict[str, Any]:
        """
        Process the PDF and return a dictionary containing all extracted
        information about the case.
        """
        return {
            **self.parse_general_info(),
            'history': self.parse_history(),
            'linked_requests': self.parse_requests(),
            'involved_team': self.parse_team(),
            'traces': self.parse_traces(),
            'involved_people': self.parse_people()
        }

    @staticmethod
    def extract_data_to_case_info(pdf_data: Dict[str, Any]) -> CaseInfo:
        """
        Convert the extracted PDF data to a CaseInfo object.
        
        Args:
            pdf_data: The dictionary with extracted PDF data.
            
        Returns:
            A populated CaseInfo object.
        """
        case_info = CaseInfo()
        
        # Basic information
        case_info.case_number = pdf_data.get('case_number')
        case_info.case_year = pdf_data.get('case_year')
        case_info.report_number = pdf_data.get('report_number')
        case_info.rai = pdf_data.get('rai')
        case_info.requesting_unit = pdf_data.get('requesting_unit')
        case_info.authority = pdf_data.get('authority')
        case_info.city = pdf_data.get('city')
        case_info.address = pdf_data.get('address')
        case_info.address_complement = pdf_data.get('address_complement')
        case_info.coordinates = pdf_data.get('coordinates')
        
        # Lists of items
        case_info.history = [HistoryItem(**item) for item in pdf_data.get('history', [])]
        case_info.linked_requests = [LinkedRequest(**req) for req in pdf_data.get('linked_requests', [])]
        case_info.involved_team = [TeamMember(**member) for member in pdf_data.get('involved_team', [])]
        case_info.traces = [Trace(**trace) for trace in pdf_data.get('traces', [])]
        case_info.involved_people = [InvolvedPerson(**person) for person in pdf_data.get('involved_people', [])]
        
        return case_info

    @staticmethod
    def process_pdf(pdf_source: Union[str, bytes, Path]) -> Optional[CaseInfo]:
        """
        Process a PDF file and convert the extracted data into a CaseInfo object.
        
        Args:
            pdf_source: Path to the PDF file or PDF content as bytes.
            
        Returns:
            CaseInfo object with the extracted data or None if processing fails.
        """
        try:
            processor = PdfProcessor(pdf_source)
            pdf_data = processor.process()
            return PdfProcessor.extract_data_to_case_info(pdf_data)
        except Exception as e:
            logger.exception(f"Error processing PDF: {e}")
            return None

def is_valid_pdf(pdf_data: bytes) -> bool:
    """
    Verify if the provided data is a valid PDF file.
    
    Args:
        pdf_data: Raw bytes of the file to validate.
        
    Returns:
        True if the data appears to be a valid PDF, False otherwise.
    """
    try:
        # Check PDF header signature
        if not pdf_data.startswith(b'%PDF-'):
            return False
        
        # Try to parse with PdfReader
        reader = PdfReader(io.BytesIO(pdf_data))
        
        # Check if the document has at least one page
        if len(reader.pages) < 1:
            return False
            
        return True
    except Exception as e:
        logger.warning(f"PDF validation failed: {e}")
        return False

def extract_text_from_pdf(pdf_path: Union[str, bytes, Path]) -> str:
    """
    Extract text content from a PDF file.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        Extracted text content
    """
    processor = PdfProcessor(pdf_path)
    return processor.extract_text()

def extract_metadata_from_pdf(pdf_path: Union[str, bytes, Path]) -> Dict[str, Any]:
    """
    Extract metadata from a PDF file.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        Dictionary containing metadata
    """
    processor = PdfProcessor(pdf_path)
    return processor.parse_general_info() 