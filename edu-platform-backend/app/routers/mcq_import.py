"""MCQ import endpoints for the paper editor (admins and MCQ editors).

PDF:  /pdf/extract (split into parts) → /pdf/convert per part (Groq)
      → /normalize.  The browser drives the loop, one short request per part,
      waiting out Groq's free-tier 429s — no request runs for minutes.
      mode="image" (default, "Best accuracy"): one rendered page per part, read
      by the vision model — keeps fractions, powers, log bases, overbars and
      symbols, and works for scanned papers. mode="text" ("Faster"): the PDF's
      text layer, several pages per part — fine for text-only papers.
JSON: /normalize directly.

Nothing here writes to the database: the result goes into the editor, and
is only saved when the person reviews it and clicks Save.
"""
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.limiter import limiter
from app.core.mcq_import import (
    MAX_IMAGE_B64, MAX_PART_CHARS, AIRateLimited, AIUnavailable, ImportProblem,
    chunk_pages, convert_part, extract_pages, image_parts, next_carry, normalize_import, render_pages,
)
from app.dependencies import require_mcq_author

router = APIRouter(prefix="/api/admin/mcq-import", tags=["Admin — MCQ Import"])


@router.post("/pdf/extract")
async def extract_pdf(
    paper: UploadFile = File(...),
    answer_key: Optional[UploadFile] = File(None),
    mode: str = Form("image"),
    author: dict = Depends(require_mcq_author),
):
    """Splits the question paper (and an optional separate answer-key PDF)
    into parts sized for one AI call each: page images or text."""
    if mode not in ("image", "text"):
        raise HTTPException(status_code=400, detail='mode must be "image" or "text".')
    paper_bytes = await paper.read()
    key_bytes = await answer_key.read() if answer_key is not None else None
    try:
        # pdfium rendering and pypdf parsing are CPU-bound; keep them off the event loop.
        if mode == "image":
            pages = await run_in_threadpool(render_pages, paper_bytes, "question paper")
            parts = image_parts(pages, "Question paper")
            if key_bytes is not None:
                parts += image_parts(await run_in_threadpool(render_pages, key_bytes, "answer key PDF"), "Answer key")
        else:
            pages = await run_in_threadpool(extract_pages, paper_bytes, "question paper")
            parts = chunk_pages(pages, "Question paper")
            if key_bytes is not None:
                parts += chunk_pages(await run_in_threadpool(extract_pages, key_bytes, "answer key PDF"), "Answer key")
    except ImportProblem as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"parts": parts, "pages": len(pages), "mode": mode}


class ConvertBody(BaseModel):
    # Exactly one of these: a text part, or one page image (base64 JPEG).
    text: Optional[str] = Field(None, min_length=1, max_length=MAX_PART_CHARS)
    image: Optional[str] = Field(None, min_length=1, max_length=MAX_IMAGE_B64)
    # The previous part's "carry" (see next_carry): where it stopped — an open
    # case study, the last question number, whether that one's answer was
    # seen. Sent back unchanged. A plain string is the older case-only form.
    carry: Optional[Union[Dict[str, Any], str]] = None


@router.post("/pdf/convert")
@limiter.limit("40/minute")
async def convert_pdf_part(request: Request, body: ConvertBody, author: dict = Depends(require_mcq_author)):
    """Converts one part with Groq. A 429 carries retryAfter (seconds) so the
    browser can show a countdown and retry the same part. The reply's "carry"
    goes with the next part."""
    if (body.text is None) == (body.image is None):
        raise HTTPException(status_code=400, detail="Send either the part's text or its page image.")
    api_key = get_settings().groq_api_key
    if not api_key:
        raise HTTPException(status_code=503, detail="Import from PDF isn't set up on the server — add GROQ_API_KEY to the backend environment.")
    try:
        result = await convert_part(body.text, api_key, case_context=body.carry, image=body.image)
        return {"result": result, "carry": next_carry(result, body.carry)}
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
