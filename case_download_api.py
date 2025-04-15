import os
import re
import io
import zipfile
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse

app = FastAPI()

# --- Config ---
DATA_ROOT = os.path.join(os.path.dirname(__file__), "data", "2025")
SECRET_TOKEN = "test_token_123"  # Change this to a secure value
CASE_ID_PATTERN = re.compile(r"^SEPPATRI_\d+_\d+_\d{4}$")

# --- Auth Dependency ---
def verify_token(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = auth_header.split(" ", 1)[1]
    if token != SECRET_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

# --- Health Endpoint ---
@app.get("/health")
def health_check():
    """Basic health check endpoint."""
    return {"status": "ok"}

# --- Download Endpoint ---
@app.get("/download/{case_id}")
def download_case(case_id: str, auth=Depends(verify_token)):
    # Validate case ID format
    if not CASE_ID_PATTERN.match(case_id):
        raise HTTPException(status_code=400, detail="Invalid case ID format")

    case_dir = os.path.join(DATA_ROOT, case_id)
    if not os.path.isdir(case_dir):
        raise HTTPException(status_code=404, detail="Case not found")

    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(case_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, case_dir)
                zipf.write(file_path, arcname)
    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={case_id}.zip"}
    )

# --- Usage ---
# Run with: uvicorn case_download_api:app --reload
# Access: GET /download/{case_id} with header Authorization: Bearer YOUR_SECRET_TOKEN 