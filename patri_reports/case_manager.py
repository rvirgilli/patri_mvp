import os
import logging
import json
import uuid
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Union, Tuple, Any

from .models.case import CaseInfo, TextEvidence, PhotoEvidence, AudioEvidence, CaseNote
from .utils import file_ops
from .utils.pdf_processor import PdfProcessor, is_valid_pdf
from .utils.config import CASE_ID_PREFIX

logger = logging.getLogger(__name__)

class CaseManager:
    """Manages case data structures and persistence.
    
    Handles case creation, evidence collection, and metadata updates.
    """
    
    def __init__(self, data_dir: str = "data"):
        """Initialize the CaseManager.
        
        Args:
            data_dir: Base directory for storing all case data.
        """
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        logger.info(f"CaseManager initialized with data directory: {self.data_dir}")
    
    def create_new_case(self) -> CaseInfo:
        """Create a new, empty case with a unique ID.
        
        Returns:
            A new CaseInfo object.
        """
        case_info = CaseInfo()
        case_id = case_info.case_id  # This is a temporary UUID-based ID
        
        # We'll use the current year for directory creation
        # This may be updated later when we get PDF data
        current_year = datetime.now().year
        
        # Create the case directory structure
        case_path = file_ops.create_case_directory_structure(self.data_dir, case_id, current_year)
        if not case_path:
            raise RuntimeError(f"Failed to create directory structure for case {case_id}")
        
        # Save initial empty case info
        file_ops.save_case_info(case_info, case_path)
        logger.info(f"Created new case with initial ID: {case_id}")
        return case_info
    
    def get_case_path(self, case_id: str, year: Optional[int] = None) -> Path:
        """Get the path to a case directory.
        
        Args:
            case_id: The case ID.
            year: The year for the case. If None, uses the current year.
        
        Returns:
            The path to the case directory.
        """
        if year is None:
            # For existing cases without year info, try to extract from case_id
            # Format is expected to be SEPPATRI_case_number_report_number_case_year
            parts = case_id.split('_')
            if len(parts) >= 4 and parts[-1].isdigit():
                year = int(parts[-1])
            else:
                year = datetime.now().year
                
        return Path(self.data_dir) / str(year) / case_id
    
    def load_case(self, case_id: str, year: Optional[int] = None) -> Optional[CaseInfo]:
        """Load a case by its ID.
        
        Args:
            case_id: The unique identifier for the case.
            year: The year for the case. If None, tries to determine from case_id.
            
        Returns:
            The CaseInfo object if found, None otherwise.
        """
        case_path = self.get_case_path(case_id, year)
        return file_ops.load_case_info(case_path)
    
    def save_case(self, case_info: CaseInfo) -> bool:
        """Save a case to disk.
        
        Args:
            case_info: The case information to save.
            
        Returns:
            True if successful, False otherwise.
        """
        try:
            # Determine year from case_info
            year = case_info.case_year or datetime.now().year
            
            # Get correct case path
            case_path = self.get_case_path(case_info.case_id, year)
            
            # Ensure the directory exists 
            case_path.mkdir(parents=True, exist_ok=True)
            photos_dir = case_path / "photos"
            audio_dir = case_path / "audio"
            photos_dir.mkdir(exist_ok=True)
            audio_dir.mkdir(exist_ok=True)
            
            # Save the case info
            file_ops.save_case_info(case_info, case_path)
            return True
        except Exception as e:
            logger.error(f"Failed to save case {case_info.case_id}: {e}")
            return False
    
    def save_pdf(self, case_id: str, pdf_data: bytes, year: Optional[int] = None, filename: str = "case_pdf.pdf") -> Optional[str]:
        """Save the occurrence PDF for a case.
        
        Args:
            case_id: The case ID.
            pdf_data: The raw PDF file data.
            year: The year for the case. If None, tries to determine from case_id.
            filename: The name to use for the saved PDF.
            
        Returns:
            The path to the saved PDF if successful, None otherwise.
        """
        case_path = self.get_case_path(case_id, year)
        pdf_path = case_path / filename
        
        if file_ops.save_evidence_file(pdf_data, pdf_path):
            # Update case info with PDF path
            case_info = self.load_case(case_id, year)
            if case_info:
                case_info.case_pdf_path = str(pdf_path)
                case_info.timestamps.case_received = datetime.now()
                self.save_case(case_info)
            
            return str(pdf_path)
        return None
    
    def process_pdf(self, pdf_data: bytes) -> Optional[CaseInfo]:
        """Process a PDF file to extract case information and create a new case.
        
        1. Validates the PDF data
        2. Creates a new case
        3. Saves the PDF
        4. Extracts data from the PDF
        5. Updates the case with extracted information
        6. Generates a proper case ID and reorganizes if needed
        
        Args:
            pdf_data: The raw PDF file data.
            
        Returns:
            The updated CaseInfo object if successful, None otherwise.
        """
        # First validate the PDF
        if not is_valid_pdf(pdf_data):
            logger.error("Invalid PDF data provided")
            return None
            
        # Create a new case (with temporary UUID-based ID)
        case_info = self.create_new_case()
        temp_case_id = case_info.case_id
        
        # Save the PDF
        pdf_path = self.save_pdf(temp_case_id, pdf_data, filename="case_pdf.pdf")
        if not pdf_path:
            logger.error(f"Failed to save PDF for case {temp_case_id}")
            return None
        
        # Extract data from PDF
        try:
            # Process the PDF and extract the data
            processed_case_info = PdfProcessor.process_pdf(pdf_data)
            if not processed_case_info:
                logger.error(f"Failed to extract data from PDF for case {temp_case_id}")
                return None
                
            # Transfer the extracted data to our case
            case_info.case_number = processed_case_info.case_number
            case_info.case_year = processed_case_info.case_year
            case_info.report_number = processed_case_info.report_number
            case_info.rai = processed_case_info.rai
            case_info.requesting_unit = processed_case_info.requesting_unit
            case_info.authority = processed_case_info.authority
            case_info.city = processed_case_info.city
            case_info.address = processed_case_info.address
            case_info.address_complement = processed_case_info.address_complement
            case_info.coordinates = processed_case_info.coordinates
            case_info.history = processed_case_info.history
            case_info.linked_requests = processed_case_info.linked_requests
            case_info.involved_team = processed_case_info.involved_team
            case_info.traces = processed_case_info.traces
            case_info.involved_people = processed_case_info.involved_people
            
            # Now generate the proper case ID based on the PDF data
            if case_info.case_number and case_info.report_number and case_info.case_year:
                new_case_id = f"{CASE_ID_PREFIX}_{case_info.case_number}_{case_info.report_number}_{case_info.case_year}"
                
                # Save the new case ID
                old_case_id = case_info.case_id
                case_info.case_id = new_case_id
                
                # Get paths for both old and new case locations
                old_case_path = self.get_case_path(old_case_id, datetime.now().year)  # Temporary ID uses current year
                new_case_path = self.get_case_path(new_case_id, case_info.case_year)
                
                # Create the new case directory if it doesn't already exist
                try:
                    # Create new directory structure
                    if not new_case_path.exists():
                        file_ops.create_case_directory_structure(self.data_dir, new_case_id, case_info.case_year)
                    
                    # Save the case info to the new location
                    file_ops.save_case_info(case_info, new_case_path)
                    
                    # Copy all files from old path to new path
                    for item in old_case_path.glob('**/*'):
                        if item.is_file() and item.name != "case_info.json":  # Skip case_info.json as we just created it
                            target = new_case_path / item.relative_to(old_case_path)
                            target.parent.mkdir(parents=True, exist_ok=True)
                            import shutil
                            shutil.copy2(item, target)
                    
                    # Update file paths in case_info to point to new locations
                    case_info.case_pdf_path = str(new_case_path / "case_pdf.pdf")
                    
                    # Update evidence file paths
                    for evidence in case_info.evidence:
                        if hasattr(evidence, "file_path") and evidence.file_path:
                            old_path = Path(evidence.file_path)
                            new_path = new_case_path / old_path.relative_to(old_case_path)
                            evidence.file_path = str(new_path)
                    
                    # Save updated case info
                    file_ops.save_case_info(case_info, new_case_path)
                    
                    # Remove old directory
                    import shutil
                    shutil.rmtree(old_case_path)
                    
                    logger.info(f"Renamed case from {old_case_id} to {new_case_id} and moved to appropriate year directory")
                except Exception as e:
                    logger.error(f"Failed to reorganize case from {old_case_id} to {new_case_id}: {e}")
                    # Don't fail the whole process if reorganization fails
                    # Just keep the original case ID and location
                    case_info.case_id = old_case_id
            
            # Save the updated case info
            if not self.save_case(case_info):
                logger.error(f"Failed to save updated case info for case {case_info.case_id}")
                return None
                
            logger.info(f"Successfully processed PDF and extracted data for case {case_info.case_id}")
            return case_info
            
        except Exception as e:
            logger.exception(f"Error processing PDF for case {temp_case_id}: {e}")
            return None
    
    def add_text_evidence(self, case_id: str, text_content: str, year: Optional[int] = None) -> Optional[str]:
        """Add a text note as evidence to a case.
        
        Args:
            case_id: The case ID.
            text_content: The text content to add.
            year: The year for the case. If None, tries to determine from case_id.
            
        Returns:
            The evidence_id if successful, None otherwise.
        """
        case_info = self.load_case(case_id, year)
        if not case_info:
            logger.error(f"Failed to add text evidence: Case {case_id} not found")
            return None
        
        # Create new text evidence
        text_evidence = TextEvidence(content=text_content)
        
        # Set attendance_started timestamp if this is the first evidence
        if not case_info.timestamps.attendance_started:
            case_info.timestamps.attendance_started = datetime.now()
        
        # Add to case
        case_info.evidence.append(text_evidence)
        
        # Save case
        if not self.save_case(case_info):
            logger.error(f"Failed to save case after adding text evidence")
            return None
        
        return text_evidence.evidence_id
    
    def add_photo_evidence(self, case_id: str, photo_data: bytes, year: Optional[int] = None, filename: Optional[str] = None) -> Optional[str]:
        """Add a photo as evidence to a case.
        
        Args:
            case_id: The case ID.
            photo_data: The raw photo data.
            year: The year for the case. If None, tries to determine from case_id.
            filename: Optional filename to use (if None, a UUID-based name is generated).
            
        Returns:
            The evidence_id if successful, None otherwise.
        """
        case_info = self.load_case(case_id, year)
        if not case_info:
            logger.error(f"Failed to add photo evidence: Case {case_id} not found")
            return None
        
        # Generate filename if not provided
        if not filename:
            ext = ".jpg"  # Default extension
            filename = f"{uuid.uuid4()}{ext}"
        
        # Ensure the file has a valid extension
        if not any(filename.lower().endswith(ext) for ext in ('.jpg', '.jpeg', '.png')):
            filename += '.jpg'
        
        # Save photo to the photos directory
        case_path = self.get_case_path(case_id, year)
        photos_dir = case_path / "photos"
        photo_path = photos_dir / filename
        
        if not file_ops.save_evidence_file(photo_data, photo_path):
            logger.error(f"Failed to save photo file for case {case_id}")
            return None
        
        # Create new photo evidence
        photo_evidence = PhotoEvidence(
            file_path=str(photo_path),
            is_fingerprint=False
        )
        
        # Set attendance_started timestamp if this is the first evidence
        if not case_info.timestamps.attendance_started:
            case_info.timestamps.attendance_started = datetime.now()
        
        # Add to case
        case_info.evidence.append(photo_evidence)
        
        # Save case
        if not self.save_case(case_info):
            logger.error(f"Failed to save case after adding photo evidence")
            return None
        
        return photo_evidence.evidence_id
    
    def add_audio_evidence(self, case_id: str, audio_data: bytes, year: Optional[int] = None, transcript: Optional[str] = None, filename: Optional[str] = None) -> Optional[str]:
        """Add an audio recording as evidence to a case.
        
        Args:
            case_id: The case ID.
            audio_data: The raw audio data.
            year: The year for the case. If None, tries to determine from case_id.
            transcript: Optional transcript of the audio.
            filename: Optional filename to use (if None, a UUID-based name is generated).
            
        Returns:
            The evidence_id if successful, None otherwise.
        """
        case_info = self.load_case(case_id, year)
        if not case_info:
            logger.error(f"Failed to add audio evidence: Case {case_id} not found")
            return None
        
        # Generate filename if not provided
        if not filename:
            ext = ".ogg"  # Default extension for Telegram voice notes
            filename = f"{uuid.uuid4()}{ext}"
        
        # Ensure the file has a valid extension
        if not any(filename.lower().endswith(ext) for ext in ('.ogg', '.mp3', '.m4a', '.wav')):
            filename += '.ogg'
        
        # Save audio to the audio directory
        case_path = self.get_case_path(case_id, year)
        audio_dir = case_path / "audio"
        audio_path = audio_dir / filename
        
        if not file_ops.save_evidence_file(audio_data, audio_path):
            logger.error(f"Failed to save audio file for case {case_id}")
            return None
        
        # Create new audio evidence
        audio_evidence = AudioEvidence(
            file_path=str(audio_path),
            transcript=transcript
        )
        
        # Set attendance_started timestamp if this is the first evidence
        if not case_info.timestamps.attendance_started:
            case_info.timestamps.attendance_started = datetime.now()
        
        # Add to case
        case_info.evidence.append(audio_evidence)
        
        # Save case
        if not self.save_case(case_info):
            logger.error(f"Failed to save case after adding audio evidence")
            return None
        
        return audio_evidence.evidence_id
    
    def update_evidence_metadata(self, case_id: str, evidence_id: str, metadata: Dict[str, Any], year: Optional[int] = None) -> bool:
        """Update metadata for a specific piece of evidence.
        
        Args:
            case_id: The case ID.
            evidence_id: The ID of the evidence to update.
            metadata: Dictionary of metadata to update.
            year: The year for the case. If None, tries to determine from case_id.
            
        Returns:
            True if successful, False otherwise.
        """
        case_info = self.load_case(case_id, year)
        if not case_info:
            logger.error(f"Failed to update evidence: Case {case_id} not found")
            return False
        
        # Find the evidence item
        for i, evidence in enumerate(case_info.evidence):
            if evidence.evidence_id == evidence_id:
                # Update each metadata field
                for key, value in metadata.items():
                    if hasattr(evidence, key):
                        setattr(evidence, key, value)
                    else:
                        logger.warning(f"Ignoring unknown metadata field '{key}' for evidence {evidence_id}")
                
                # Save case
                if not self.save_case(case_info):
                    logger.error(f"Failed to save case after updating evidence metadata")
                    return False
                
                return True
        
        logger.error(f"Evidence with ID {evidence_id} not found in case {case_id}")
        return False
    
    def finalize_case(self, case_id: str, year: Optional[int] = None) -> bool:
        """Mark a case as finalized (collection finished).
        
        Args:
            case_id: The case ID.
            year: The year for the case. If None, tries to determine from case_id.
            
        Returns:
            True if successful, False otherwise.
        """
        case_info = self.load_case(case_id, year)
        if not case_info:
            logger.error(f"Failed to finalize case: Case {case_id} not found")
            return False
        
        # Set the collection_finished timestamp
        case_info.timestamps.collection_finished = datetime.now()
        
        # Save case
        if not self.save_case(case_info):
            logger.error(f"Failed to save case after finalizing")
            return False
        
        logger.info(f"Case {case_id} has been finalized")
        return True
    
    def list_cases(self) -> List[Dict[str, Any]]:
        """List all cases in the data directory.
        
        Returns:
            A list of basic case information dictionaries.
        """
        cases = []
        
        try:
            # Scan all year directories
            for year_dir in Path(self.data_dir).glob('*'):
                if not year_dir.is_dir() or not year_dir.name.isdigit():
                    continue
                
                # Scan case directories within each year
                for case_dir in year_dir.glob('*'):
                    if not case_dir.is_dir():
                        continue
                    
                    case_info_path = case_dir / "case_info.json"
                    if case_info_path.exists():
                        case_info = file_ops.load_case_info(case_dir)
                        if case_info:
                            cases.append({
                                "case_id": case_info.case_id,
                                "display_id": case_info.get_display_id(),
                                "year": case_info.case_year or int(year_dir.name),
                                "created": case_info.timestamps.case_received,
                                "status": "Finalized" if case_info.timestamps.collection_finished else "In Progress"
                            })
        except Exception as e:
            logger.error(f"Error listing cases: {e}")
        
        return cases
    
    def add_case_note(self, case_id: str, text_content: str, audio_data: Optional[bytes] = None, 
                     year: Optional[int] = None, duration_seconds: Optional[int] = None,
                     filename: Optional[str] = None) -> Optional[str]:
        """Add a case note with optional audio recording.
        
        Args:
            case_id: The case ID.
            text_content: The text content (could be user input or transcription).
            audio_data: Optional raw audio data.
            year: The year for the case. If None, tries to determine from case_id.
            duration_seconds: Optional duration of the audio in seconds.
            filename: Optional filename to use for audio (if None, a UUID-based name is generated).
            
        Returns:
            The evidence_id if successful, None otherwise.
        """
        case_info = self.load_case(case_id, year)
        if not case_info:
            logger.error(f"Failed to add case note: Case {case_id} not found")
            return None
        
        # Create new case note
        case_note = CaseNote(
            content=text_content
        )
        
        # Handle audio data if provided
        if audio_data:
            # Generate filename if not provided
            if not filename:
                ext = ".ogg"  # Default extension for Telegram voice notes
                filename = f"{uuid.uuid4()}{ext}"
            
            # Ensure the file has a valid extension
            if not any(filename.lower().endswith(ext) for ext in ('.ogg', '.mp3', '.m4a', '.wav')):
                filename += '.ogg'
            
            # Save audio to the audio directory
            case_path = self.get_case_path(case_id, year)
            audio_dir = case_path / "audio"
            audio_path = audio_dir / filename
            
            if not file_ops.save_evidence_file(audio_data, audio_path):
                logger.error(f"Failed to save audio file for case {case_id}")
                return None
            
            # Update case note with audio info
            case_note.audio_file_path = str(audio_path)
            case_note.duration_seconds = duration_seconds
        
        # Set attendance_started timestamp if this is the first evidence
        if not case_info.timestamps.attendance_started:
            case_info.timestamps.attendance_started = datetime.now()
        
        # Add to case
        case_info.evidence.append(case_note)
        
        # Save case
        if not self.save_case(case_info):
            logger.error(f"Failed to save case after adding case note")
            return None
        
        return case_note.evidence_id
    
    def update_case_location(self, case_id: str, latitude: float, longitude: float, year: Optional[int] = None) -> bool:
        """Update the case location with precise coordinates.
        
        Args:
            case_id: The case ID.
            latitude: The latitude coordinate.
            longitude: The longitude coordinate.
            year: The year for the case. If None, tries to determine from case_id.
            
        Returns:
            True if successful, False otherwise.
        """
        try:
            case_info = self.load_case(case_id, year)
            if not case_info:
                logger.error(f"Failed to load case {case_id} for location update")
                return False
                
            # Update the coordinates
            case_info.coordinates = (latitude, longitude)
            
            # Save the updated case
            return self.save_case(case_info)
        except Exception as e:
            logger.error(f"Error updating location for case {case_id}: {e}")
            return False
    
    def update_case_attendance_location(self, case_id: str, latitude: float, longitude: float, year: Optional[int] = None) -> bool:
        """Update the case attendance location with precise coordinates.
        
        This stores a single location for the case in the attendance_location field.
        If a previous location was stored, it will be replaced.
        
        Args:
            case_id: The case ID.
            latitude: The latitude coordinate.
            longitude: The longitude coordinate.
            year: The year for the case. If None, tries to determine from case_id.
            
        Returns:
            True if successful, False otherwise.
        """
        try:
            case_info = self.load_case(case_id, year)
            if not case_info:
                logger.error(f"Failed to load case {case_id} for attendance location update")
                return False
                
            # Update the attendance_location field
            case_info.attendance_location = {
                "latitude": latitude,
                "longitude": longitude,
                "timestamp": datetime.now().isoformat()
            }
            
            # Save the updated case
            return self.save_case(case_info)
        except Exception as e:
            logger.error(f"Error updating attendance location for case {case_id}: {e}")
            return False
    
    def update_llm_data(self, case_id: str, summary: Optional[str] = None, 
                       year: Optional[int] = None) -> bool:
        """Update the case with LLM-generated summary.
        
        Args:
            case_id: The case ID.
            summary: The LLM-generated summary text.
            year: The year for the case. If None, tries to determine from case_id.
            
        Returns:
            True if successful, False otherwise.
        """
        try:
            case_info = self.load_case(case_id, year)
            if not case_info:
                logger.error(f"Failed to load case {case_id} for LLM data update")
                return False
                
            # Update the summary if provided
            if summary is not None:
                case_info.llm_summary = summary
                
            # Save the updated case
            return self.save_case(case_info)
        except Exception as e:
            logger.error(f"Error updating LLM data for case {case_id}: {e}")
            return False
    
    def is_pdf_corrupted(self, pdf_path: Path) -> bool:
        """
        Checks if a PDF file is corrupted or invalid.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            True if the PDF appears to be corrupted, False otherwise
        """
        from patri_reports.utils.file_ops import is_corrupted_pdf
        return is_corrupted_pdf(pdf_path)

    async def save_pdf_file(self, file_data: bytes, pdf_path: Path) -> bool:
        """
        Saves PDF file data to disk using async file operations.
        
        Args:
            file_data: The raw PDF bytes
            pdf_path: Path where to save the PDF file
            
        Returns:
            True if successful, False otherwise
            
        Raises:
            NetworkError: If there's a network or I/O error during file saving
            TimeoutError: If the operation times out
        """
        from patri_reports.utils.file_ops import async_save_evidence_file
        from patri_reports.utils.error_handler import NetworkError, TimeoutError
        
        try:
            success, elapsed_time = await async_save_evidence_file(file_data, pdf_path)
            if not success:
                logger.error(f"Failed to save PDF file to {pdf_path}")
                return False
                
            logger.info(f"Successfully saved PDF file ({len(file_data)/1024:.1f} KB) in {elapsed_time:.2f}s")
            return True
            
        except TimeoutError as e:
            logger.error(f"Timeout saving PDF file to {pdf_path}: {e}")
            raise  # Re-raise to be handled by the workflow manager
            
        except Exception as e:
            logger.exception(f"Error saving PDF file to {pdf_path}: {e}")
            raise NetworkError(f"Failed to save PDF file: {str(e)}")  # Convert to NetworkError

    def delete_case(self, case_id: str) -> bool:
        """
        Deletes a case directory and all its contents.
        
        Args:
            case_id: The ID of the case to delete
            
        Returns:
            True if successful, False otherwise
        """
        import shutil
        try:
            case_path = self.get_case_path(case_id)
            if case_path and case_path.exists():
                logger.info(f"Deleting case directory for case {case_id}: {case_path}")
                shutil.rmtree(case_path)
                return True
            return False
        except Exception as e:
            logger.exception(f"Error deleting case {case_id}: {e}")
            return False

    def cleanup_old_cases(self, max_age_days: int = 30) -> dict:
        """
        Cleans up completed cases older than the specified age.
        
        Args:
            max_age_days: Maximum age in days before a completed case is considered for cleanup
            
        Returns:
            Dictionary with counts of cases processed and removed
        """
        from patri_reports.utils.error_handler import cleanup_old_cases
        return cleanup_old_cases(self.data_dir, max_age_days)
    
    def extract_pdf_info(self, pdf_path: str) -> Optional[Dict]:
        """Extract information from a PDF file without creating a case.
        
        Args:
            pdf_path: Path to the PDF file.
            
        Returns:
            Dictionary with extracted information, or None if extraction failed.
        """
        try:
            # Check if path exists
            if not os.path.exists(pdf_path):
                logger.error(f"PDF file not found at {pdf_path}")
                return None

            # Extract PDF text and data
            pdf_processor = PdfProcessor(pdf_path)
            extracted_info = pdf_processor.process()
            if not extracted_info:
                logger.error(f"Failed to extract information from PDF at {pdf_path}")
                return None
                
            logger.info(f"Successfully extracted info from {pdf_path}")
            return extracted_info
        except Exception as e:
            logger.error(f"Error in extract_pdf_info: {e}")
            return None

    def create_case(self, case_id: str, pdf_filename: str) -> Optional[Path]:
        """Create a case directory structure for a new case.
        
        Args:
            case_id: The case ID.
            pdf_filename: The name of the PDF file for the case.
            
        Returns:
            The path to the case directory if successful, None otherwise.
        """
        try:
            # Extract year from case_id or use current year
            year = None
            parts = case_id.split('_')
            if len(parts) >= 4 and parts[-1].isdigit():
                year = int(parts[-1])
            else:
                year = datetime.now().year
                
            # Get the case path
            case_path = self.get_case_path(case_id, year)
            
            # Create the directory structure
            case_path.mkdir(parents=True, exist_ok=True)
            
            # Create subdirectories for evidence
            (case_path / "photos").mkdir(exist_ok=True)
            (case_path / "audio").mkdir(exist_ok=True)
            
            # Create an initial empty case info
            case_info = CaseInfo()
            case_info.case_id = case_id
            case_info.case_year = year
            case_info.case_pdf_path = pdf_filename
            
            # Save the initial case info
            file_ops.save_case_info(case_info, case_path)
            
            logger.info(f"Created case directory structure for case {case_id}")
            return case_path
        except Exception as e:
            logger.error(f"Failed to create case directory structure for case {case_id}: {e}")
            return None

    def register_pdf_in_case(self, case_id: str, pdf_path: str) -> bool:
        """Register an existing PDF file in a case.
        
        Args:
            case_id: The case ID.
            pdf_path: Path to the PDF file.
            
        Returns:
            True if successful, False otherwise.
        """
        try:
            case_info = self.load_case(case_id)
            if not case_info:
                logger.error(f"Cannot register PDF - case {case_id} not found")
                return False
                
            # Update case with PDF path
            case_info.case_pdf_path = pdf_path
            case_info.timestamps.case_received = datetime.now()
            self.save_case(case_info)
            
            logger.info(f"Registered PDF {pdf_path} with case {case_id}")
            return True
        except Exception as e:
            logger.error(f"Error registering PDF in case {case_id}: {e}")
            return False
            
    def update_case_with_extracted_info(self, case_id: str, extracted_info: Dict) -> bool:
        """Update a case with extracted information from PDF.
        
        Args:
            case_id: The case ID.
            extracted_info: Dictionary with extracted information.
            
        Returns:
            True if successful, False otherwise.
        """
        try:
            case_info = self.load_case(case_id)
            if not case_info:
                logger.error(f"Cannot update case - case {case_id} not found")
                return False
                
            # Update case with extracted info
            if isinstance(extracted_info, dict):
                # Update attributes from dictionary
                for key, value in extracted_info.items():
                    if hasattr(case_info, key):
                        setattr(case_info, key, value)
            else:
                # Try to transfer attributes object to object
                for attr in dir(extracted_info):
                    if not attr.startswith('_') and hasattr(case_info, attr):
                        setattr(case_info, attr, getattr(extracted_info, attr))
            
            # Save updated case
            self.save_case(case_info)
            
            logger.info(f"Updated case {case_id} with extracted information")
            return True
        except Exception as e:
            logger.error(f"Error updating case {case_id} with extracted info: {e}")
            return False 