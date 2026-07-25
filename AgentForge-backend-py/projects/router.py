"""
ChatBot Platform — Projects Router
CRUD for projects and their system prompts.
All endpoints require a valid Supabase JWT.

GET    /api/projects           — list all projects for the authenticated user
POST   /api/projects           — create a new project (+ optional initial prompt)
GET    /api/projects/{id}      — get project detail with active prompt
PUT    /api/projects/{id}      — update project name / description
DELETE /api/projects/{id}      — delete project (cascades prompts + conversations)
POST   /api/projects/{id}/prompt — set or update the active prompt
"""
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
import io
from loguru import logger

from auth.middleware import SupabaseUser, get_supabase_user
from config import get_settings
from projects.schemas import (
    CreateProjectRequest,
    MessageOut,
    ProjectListOut,
    ProjectOut,
    ProjectFileOut,
    PromptOut,
    SetPromptRequest,
    UpdateProjectRequest,
)

router = APIRouter(prefix="/api/projects", tags=["Projects"])

settings = get_settings()


# ── Supabase REST helper ───────────────────────────────────────────────────────

def _supabase_headers() -> dict:
    """Headers for server-side Supabase REST calls using the service role key."""
    key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_SECRET_KEY or ""
    if not key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server is missing Supabase service key configuration.",
        )
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _rest_url(path: str) -> str:
    base = (settings.SUPABASE_URL or "").rstrip("/")
    return f"{base}/rest/v1/{path}"


async def _supabase_get(path: str, params: dict | None = None) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(_rest_url(path), headers=_supabase_headers(), params=params, timeout=10.0)
    if resp.status_code >= 400:
        logger.error(f"[Supabase GET {path}] {resp.status_code}: {resp.text}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Database read failed.")
    return resp.json()


async def _supabase_post(path: str, body: dict) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(_rest_url(path), headers=_supabase_headers(), json=body, timeout=10.0)
    if resp.status_code >= 400:
        logger.error(f"[Supabase POST {path}] {resp.status_code}: {resp.text}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Database write failed.")
    data = resp.json()
    return data[0] if isinstance(data, list) else data


async def _supabase_patch(path: str, params: dict, body: dict) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            _rest_url(path), headers=_supabase_headers(), params=params, json=body, timeout=10.0
        )
    if resp.status_code >= 400:
        logger.error(f"[Supabase PATCH {path}] {resp.status_code}: {resp.text}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Database update failed.")
    data = resp.json()
    return data[0] if isinstance(data, list) else data


async def _supabase_delete(path: str, params: dict) -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.delete(_rest_url(path), headers=_supabase_headers(), params=params, timeout=10.0)
    if resp.status_code >= 400:
        logger.error(f"[Supabase DELETE {path}] {resp.status_code}: {resp.text}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Database delete failed.")


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _get_project_owned(project_id: str, user_id: str) -> dict:
    """Fetch a project and verify it belongs to the requesting user."""
    rows = await _supabase_get("projects", params={"id": f"eq.{project_id}", "select": "*"})
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    project = rows[0]
    if project["user_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    return project


async def _get_active_prompt(project_id: str) -> dict | None:
    rows = await _supabase_get(
        "prompts",
        params={"project_id": f"eq.{project_id}", "is_active": "eq.true", "order": "created_at.desc", "limit": "1"},
    )
    return rows[0] if rows else None


def _prompt_out(p: dict) -> PromptOut:
    return PromptOut(
        id=p["id"],
        project_id=p["project_id"],
        content=p["content"],
        is_active=p["is_active"],
        created_at=p["created_at"],
    )


def _project_out(proj: dict, active_prompt: dict | None = None) -> ProjectOut:
    return ProjectOut(
        id=proj["id"],
        user_id=proj["user_id"],
        name=proj["name"],
        description=proj.get("description") or "",
        created_at=proj["created_at"],
        updated_at=proj["updated_at"],
        active_prompt=_prompt_out(active_prompt) if active_prompt else None,
    )


# ── GET /api/projects ──────────────────────────────────────────────────────────

@router.get("", response_model=ProjectListOut)
async def list_projects(
    user: Annotated[SupabaseUser, Depends(get_supabase_user)],
):
    """List all projects for the authenticated user, newest first."""
    rows = await _supabase_get(
        "projects",
        params={"user_id": f"eq.{user.id}", "order": "created_at.desc", "select": "*"},
    )
    # Fetch active prompts for all projects in one query
    project_ids = [r["id"] for r in rows]
    prompt_map: dict[str, dict] = {}
    if project_ids:
        # Fetch most recent active prompt per project
        for pid in project_ids:
            prompt_rows = await _supabase_get(
                "prompts",
                params={"project_id": f"eq.{pid}", "is_active": "eq.true", "order": "created_at.desc", "limit": "1"},
            )
            if prompt_rows:
                prompt_map[pid] = prompt_rows[0]

    return ProjectListOut(
        projects=[_project_out(r, prompt_map.get(r["id"])) for r in rows]
    )


# ── POST /api/projects ─────────────────────────────────────────────────────────

@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    body: CreateProjectRequest,
    user: Annotated[SupabaseUser, Depends(get_supabase_user)],
):
    """Create a new project with an optional initial system prompt."""
    project = await _supabase_post("projects", {
        "user_id": user.id,
        "name": body.name.strip(),
        "description": (body.description or "").strip(),
    })

    active_prompt = None
    if body.system_prompt and body.system_prompt.strip():
        active_prompt = await _supabase_post("prompts", {
            "project_id": project["id"],
            "content": body.system_prompt.strip(),
            "is_active": True,
        })

    logger.info(f"[Projects] Created project {project['id']} for user {user.id}")
    return _project_out(project, active_prompt)


# ── GET /api/projects/{id} ─────────────────────────────────────────────────────

@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: str,
    user: Annotated[SupabaseUser, Depends(get_supabase_user)],
):
    """Get a single project with its active prompt."""
    project = await _get_project_owned(project_id, user.id)
    active_prompt = await _get_active_prompt(project_id)
    return _project_out(project, active_prompt)


# ── PUT /api/projects/{id} ─────────────────────────────────────────────────────

@router.put("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: str,
    body: UpdateProjectRequest,
    user: Annotated[SupabaseUser, Depends(get_supabase_user)],
):
    """Update a project's name and/or description."""
    await _get_project_owned(project_id, user.id)  # verify ownership

    updates: dict = {}
    if body.name is not None:
        updates["name"] = body.name.strip()
    if body.description is not None:
        updates["description"] = body.description.strip()
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    project = await _supabase_patch("projects", {"id": f"eq.{project_id}"}, updates)
    active_prompt = await _get_active_prompt(project_id)
    return _project_out(project, active_prompt)


# ── DELETE /api/projects/{id} ─────────────────────────────────────────────────

@router.delete("/{project_id}", response_model=MessageOut)
async def delete_project(
    project_id: str,
    user: Annotated[SupabaseUser, Depends(get_supabase_user)],
):
    """Delete a project and all associated prompts and conversations (via FK cascade)."""
    await _get_project_owned(project_id, user.id)  # verify ownership
    await _supabase_delete("projects", {"id": f"eq.{project_id}"})
    logger.info(f"[Projects] Deleted project {project_id} for user {user.id}")
    return MessageOut(message="Project deleted successfully.")


# ── POST /api/projects/{id}/prompt ────────────────────────────────────────────

@router.post("/{project_id}/prompt", response_model=PromptOut, status_code=201)
async def set_project_prompt(
    project_id: str,
    body: SetPromptRequest,
    user: Annotated[SupabaseUser, Depends(get_supabase_user)],
):
    """
    Set or update the active system prompt for a project.
    Deactivates all existing prompts, then inserts a new active one.
    This preserves prompt history (all old prompts remain with is_active=false).
    """
    await _get_project_owned(project_id, user.id)  # verify ownership

    # Deactivate all existing active prompts for this project
    await _supabase_patch(
        "prompts",
        {"project_id": f"eq.{project_id}", "is_active": "eq.true"},
        {"is_active": False},
    )

    # Insert new active prompt
    new_prompt = await _supabase_post("prompts", {
        "project_id": project_id,
        "content": body.content.strip(),
        "is_active": True,
    })
    logger.info(f"[Projects] Updated prompt for project {project_id}")
    return _prompt_out(new_prompt)


# ── GET /api/projects/{id}/files ──────────────────────────────────────────────

@router.get("/{project_id}/files", response_model=list[ProjectFileOut])
async def list_project_files(
    project_id: str,
    user: Annotated[SupabaseUser, Depends(get_supabase_user)],
):
    """List all files uploaded to a project."""
    await _get_project_owned(project_id, user.id)
    rows = await _supabase_get(
        "project_files",
        params={"project_id": f"eq.{project_id}", "order": "created_at.desc", "select": "id,project_id,file_name,created_at"},
    )
    return [ProjectFileOut(**r) for r in rows]


# ── POST /api/projects/{id}/files ─────────────────────────────────────────────

@router.post("/{project_id}/files", response_model=ProjectFileOut, status_code=201)
async def upload_project_file(
    project_id: str,
    user: Annotated[SupabaseUser, Depends(get_supabase_user)],
    file: UploadFile = File(...),
):
    """Upload a file, extract its text, and store it in Supabase Storage."""
    await _get_project_owned(project_id, user.id)
    
    content = await file.read()
    extracted_text = ""
    filename = file.filename or "unknown"
    
    # 1. Extract text
    if filename.lower().endswith(".pdf"):
        import PyPDF2
        try:
            pdf = PyPDF2.PdfReader(io.BytesIO(content))
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    extracted_text += text + "\n"
        except Exception as e:
            logger.error(f"[Projects] PDF parse error: {e}")
            raise HTTPException(400, "Could not parse PDF file.")
    else:
        # Assume text
        try:
            extracted_text = content.decode("utf-8")
        except Exception:
            raise HTTPException(400, "Unsupported file format. Please upload PDF or Text.")
    
    if not extracted_text.strip():
        raise HTTPException(400, "File is empty or contains no readable text.")

    # 2. Upload to Supabase Storage (raw file)
    import uuid
    storage_path = f"{user.id}/{project_id}/{uuid.uuid4()}_{filename}"
    
    async with httpx.AsyncClient() as client:
        # Note: Using the REST API for storage
        storage_url = f"{(settings.SUPABASE_URL or '').rstrip('/')}/storage/v1/object/project_files/{storage_path}"
        headers = _supabase_headers()
        # For Storage upload, content-type is the file type
        headers["Content-Type"] = file.content_type or "application/octet-stream"
        
        resp = await client.post(storage_url, headers=headers, content=content, timeout=30.0)
        if resp.status_code >= 400:
            logger.error(f"[Projects] Storage upload failed: {resp.text}")
            raise HTTPException(502, "Failed to upload file to storage.")

    # 3. Save metadata and extracted text to database
    db_row = await _supabase_post("project_files", {
        "project_id": project_id,
        "file_name": filename,
        "storage_path": storage_path,
        "extracted_text": extracted_text.strip()
    })
    
    logger.info(f"[Projects] Uploaded file {filename} to project {project_id}")
    return ProjectFileOut(
        id=db_row["id"],
        project_id=db_row["project_id"],
        file_name=db_row["file_name"],
        created_at=db_row["created_at"]
    )


# ── DELETE /api/projects/{id}/files/{file_id} ─────────────────────────────────

@router.delete("/{project_id}/files/{file_id}", response_model=MessageOut)
async def delete_project_file(
    project_id: str,
    file_id: str,
    user: Annotated[SupabaseUser, Depends(get_supabase_user)],
):
    """Delete a file from the project and from storage."""
    await _get_project_owned(project_id, user.id)
    
    # 1. Get storage path
    rows = await _supabase_get(
        "project_files",
        params={"id": f"eq.{file_id}", "project_id": f"eq.{project_id}", "select": "storage_path"}
    )
    if not rows:
        raise HTTPException(404, "File not found.")
    storage_path = rows[0]["storage_path"]
    
    # 2. Delete from DB
    await _supabase_delete("project_files", {"id": f"eq.{file_id}"})
    
    # 3. Delete from storage (fire and forget)
    async with httpx.AsyncClient() as client:
        storage_url = f"{(settings.SUPABASE_URL or '').rstrip('/')}/storage/v1/object/project_files/{storage_path}"
        await client.delete(storage_url, headers=_supabase_headers(), timeout=10.0)
        
    logger.info(f"[Projects] Deleted file {file_id} from project {project_id}")
    return MessageOut(message="File deleted successfully.")
