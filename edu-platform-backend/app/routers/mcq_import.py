"""MCQ import endpoints for the paper editor (admins and MCQ editors).

PDF:  /pdf/extract (text, split into parts) → /pdf/convert per part (Groq)
      → /normalize.  The browser drives the loop, one short request per part,
      waiting out Groq's free-tier 429s — no request runs for minutes.
JSON: /normalize directly.

Nothing here writes to the database: the result goes into the editor, and
is only saved when the person reviews it and clicks Save.
"""
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.limiter import limiter
from app.core.mcq_import import (
    MAX_PART_CHARS, AIRateLimited, AIUnavailable, ImportProblem,
    case_carry, chunk_pages, convert_part, extract_pages, normalize_import,
)
from app.dependencies import require_mcq_author

router = APIRouter(prefix="/api/admin/mcq-import", tags=["Admin — MCQ Import"])


@router.post("/pdf/extract")
async def extract_pdf(
    paper: UploadFile = File(...),
    answer_key: Optional[UploadFile] = File(None),
    author: dict = Depends(require_mcq_author),
):
    """Reads the text out of the question paper (and an optional separate
    answer-key PDF) and splits it into parts sized for one AI call each."""
    try:
        pages = extract_pages(await paper.read(), "question paper")
        parts = chunk_pages(pages, "Question paper")
        if answer_key is not None:
            key_pages = extract_pages(await answer_key.read(), "answer key PDF")
            parts += chunk_pages(key_pages, "Answer key")
    except ImportProblem as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"parts": parts, "pages": len(pages)}


class ConvertBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_PART_CHARS)
    # The previous part's "carry": the passage of a case study it ended
    # inside. Sent back unchanged so a case split across parts stays whole.
    carry: Optional[str] = Field(None, max_length=4000)


@router.post("/pdf/convert")
@limiter.limit("40/minute")
async def convert_pdf_part(request: Request, body: ConvertBody, author: dict = Depends(require_mcq_author)):
    """Converts one part with Groq. A 429 carries retryAfter (seconds) so the
    browser can show a countdown and retry the same part. The reply's "carry"
    goes with the next part."""
    api_key = get_settings().groq_api_key
    if not api_key:
        raise HTTPException(status_code=503, detail="Import from PDF isn't set up on the server — add GROQ_API_KEY to the backend environment.")
    try:
        result = await convert_part(body.text, api_key, case_context=body.carry)
        return {"result": result, "carry": case_carry(result, body.carry)}
    except AIRateLimited as e:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(int(e.retry_after + 0.999))},
            content={"detail": "The free AI limit was reached for this minute.", "retryAfter": e.retry_after},
        )
    except AIUnavailable as e:
        raise HTTPException(status_code=502, detail=str(e))


class NormalizeBody(BaseModel):
    parts: List[Any] = Field(..., min_length=1, max_length=200)


@router.post("/normalize")
async def normalize(body: NormalizeBody, author: dict = Depends(require_mcq_author)):
    """Shared final step for both PDF and JSON imports: merges parts, applies
    answer keys, keeps each case study separate, and flags what needs review."""
    try:
        return normalize_import(body.parts)
    except ImportProblem as e:
        raise HTTPException(status_code=400, detail=str(e))
