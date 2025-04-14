from pydantic import BaseModel, Field
from typing import List, Optional, Tuple, Dict, Literal, Union, Any
from datetime import datetime
import uuid
import os

# --- Nested Models from PDF Data ---

class HistoryItem(BaseModel):
    title: str
    content: str

class LinkedRequest(BaseModel):
    request_number: str
    creation_date: str # Consider parsing to datetime if needed later
    responsible: str
    origin_unit: str
    affected_unit: str
    content: str

class TeamMember(BaseModel):
    name: str
    role: str

class Trace(BaseModel):
    type: str
    id: str
    examinations: str
    status: str

class InvolvedPerson(BaseModel):
    name: str
    involvement: str
    cpf: str

# --- Evidence Subtypes ---

class BaseEvidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.now)

class CaseNote(BaseEvidence):
    type: Literal["note"] = "note"
    content: str
    audio_file_path: Optional[str] = None
    duration_seconds: Optional[int] = None

# Keep TextEvidence for backward compatibility
class TextEvidence(BaseEvidence):
    type: Literal["text"] = "text"
    content: str

class PhotoEvidence(BaseEvidence):
    type: Literal["photo"] = "photo"
    file_path: str
    is_fingerprint: bool = False
    description: Optional[str] = None
    display_order: Optional[int] = None
    telegram_file_id: Optional[str] = None  # Telegram's file_id for easier resending
    audio_file_path: Optional[str] = None  # Path to audio description file if described by voice

class AudioEvidence(BaseEvidence):
    type: Literal["audio"] = "audio"
    file_path: str
    transcript: Optional[str] = None

EvidenceItem = Union[CaseNote, TextEvidence, PhotoEvidence, AudioEvidence]

# --- Timestamps ---

class CaseTimestamps(BaseModel):
    case_received: Optional[datetime] = None
    attendance_started: Optional[datetime] = None
    collection_finished: Optional[datetime] = None

# --- Main Case Information Model ---

class CaseInfo(BaseModel):
    # --- Core Case Identifiers ---
    case_id: str = Field(default_factory=lambda: str(uuid.uuid4())) # Temporary unique ID, will be replaced with formatted ID

    # --- Data from PDF ---
    case_number: Optional[int] = None
    case_year: Optional[int] = None
    report_number: Optional[int] = None
    rai: Optional[str] = None
    requesting_unit: Optional[str] = None
    authority: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    address_complement: Optional[str] = None
    coordinates: Optional[Tuple[float, float]] = None # (latitude, longitude)
    history: List[HistoryItem] = Field(default_factory=list)
    linked_requests: List[LinkedRequest] = Field(default_factory=list)
    involved_team: List[TeamMember] = Field(default_factory=list)
    traces: List[Trace] = Field(default_factory=list)
    involved_people: List[InvolvedPerson] = Field(default_factory=list)

    # --- Data from Workflow ---
    case_pdf_path: Optional[str] = None
    timestamps: CaseTimestamps = Field(default_factory=CaseTimestamps)
    evidence: List[EvidenceItem] = Field(default_factory=list)
    llm_summary: Optional[str] = None
    language: Optional[str] = None  # Language code for audio transcription, e.g., 'pt' for Portuguese
    attendance_location: Optional[Dict[str, Any]] = None  # {"latitude": float, "longitude": float, "timestamp": str}
    # Could add other status fields if needed, e.g., is_finalized: bool = False

    # Method to easily generate a user-friendly case identifier if needed
    def get_display_id(self) -> str:
        """
        Return a user-friendly display ID for the case.
        
        Returns:
            The formatted case ID as "SEPPATRI {case_number}/{report_number}/{case_year}"
        """
        # Get prefix from environment variable or use default
        case_id_prefix = os.environ.get("CASE_ID_PREFIX", "SEPPATRI").split('#')[0].strip()
        
        # Use actual case data to format the ID properly
        if self.case_number and self.report_number and self.case_year:
            return f"{case_id_prefix} {self.case_number}/{self.report_number}/{self.case_year}"
        
        # Fallback to original ID if case data is missing
        return self.case_id
        
    def to_dict(self) -> Dict:
        """
        Convert the case information to a dictionary.
        
        This method is needed for serialization when passing data to LLM APIs
        and provides better control over the conversion process than default
        Pydantic methods.
        
        Returns:
            Dict representation of the case information
        """
        try:
            # Try to use Pydantic's model_dump for v2
            if hasattr(self, "model_dump"):
                return self.model_dump()
            # Fallback to dict() for Pydantic v1
            else:
                return self.dict()
        except Exception as e:
            # Manual conversion as last resort
            data = {
                "case_id": self.case_id,
                "case_number": self.case_number,
                "case_year": self.case_year,
                "report_number": self.report_number,
                "rai": self.rai,
                "requesting_unit": self.requesting_unit,
                "authority": self.authority,
                "city": self.city,
                "address": self.address,
                "address_complement": self.address_complement,
                "coordinates": self.coordinates,
                "history": [{"title": h.title, "content": h.content} for h in self.history] if self.history else [],
                "linked_requests": [req.dict() if hasattr(req, "dict") else {"request_number": req.request_number, "content": req.content} for req in self.linked_requests] if self.linked_requests else [],
                "involved_team": [{"name": m.name, "role": m.role} for m in self.involved_team] if self.involved_team else [],
                "traces": [{"type": t.type, "id": t.id, "examinations": t.examinations, "status": t.status} for t in self.traces] if self.traces else [],
                "involved_people": [{"name": p.name, "involvement": p.involvement, "cpf": p.cpf} for p in self.involved_people] if self.involved_people else [],
                "case_pdf_path": self.case_pdf_path,
                "llm_summary": self.llm_summary,
                "language": self.language,
                "attendance_location": self.attendance_location,
            }
            return data 