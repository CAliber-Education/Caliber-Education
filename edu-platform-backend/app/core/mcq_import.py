"""MCQ import: turns a typed PDF (via Groq) or a JSON file into the MCQ
editor's section/question shape, flagging anything a person should check.

Both routes end in normalize_import(), so a PDF import and a JSON upload
follow exactly the same rules: answers are never guessed, missing ones are
left unset and flagged, and each case study lands in its own section.

Groq's free tier allows ~8,000 tokens per minute (input + output), so long
papers are split into parts (chunk_pages) that the browser sends one at a
time, waiting out 429s, rather than one long request.
"""
import base64
import io
import json
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pypdfium2 as pdfium
from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_PDF_BYTES = 15 * 1024 * 1024
MAX_PAGES = 80
# ~1,600 tokens of paper text per AI call. With the prompt (~600) and room
# for the reply (max 5,000) that keeps one request under the free tier's
# 8,000 tokens/minute.
CHUNK_CHARS = 6500
MAX_PART_CHARS = 12000

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"
# Reads page images, for "Best accuracy" imports. Maths laid out by an
# equation editor (stacked fractions, powers, log bases, overbars, symbol
# fonts) is lost when text is copied out of a PDF — 1/2 comes out as "1" and
# "2" on separate lines, P(Ā∩B̄) as P(A∩B) — but survives when the page is
# read the way a person sees it. Also works for scanned papers.
GROQ_VISION_MODEL = "qwen/qwen3.8-27b"
# Groq counts each image as 2,048 tokens; one page per request keeps prompt +
# image + reply (max 3,500) under the free tier's 8,000 tokens/minute.
RENDER_SCALE = 2.0          # ≈144 DPI: superscripts and small print stay legible
MAX_RENDER_SIDE = 2200      # cap for oversized pages (A3, posters)
MAX_IMAGE_B64 = 6 * 1024 * 1024

LEVELS = ("FINAL", "INTERMEDIATE", "FOUNDATION")
DIFFICULTIES = ("easy", "medium", "hard")
NO_ANSWER = "No answer found in the file — pick the correct option."


class ImportProblem(Exception):
    """A user-facing reason an import can't proceed (bad/scanned PDF, unreadable JSON)."""


class AIRateLimited(Exception):
    def __init__(self, retry_after: float):
        super().__init__(f"rate limited, retry after {retry_after}s")
        self.retry_after = retry_after


class AIUnavailable(Exception):
    """Groq failed or answered with something unusable."""


# ─── PDF → text parts ─────────────────────────────────────────────────────────

def _check_pdf_bytes(pdf_bytes: bytes, what: str) -> None:
    if not pdf_bytes:
        raise ImportProblem(f"The {what} is empty.")
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise ImportProblem(f"The {what} is over {MAX_PDF_BYTES // (1024 * 1024)} MB.")
    if not pdf_bytes.lstrip()[:5].startswith(b"%PDF"):
        raise ImportProblem(f"The {what} isn't a PDF file.")


def render_pages(pdf_bytes: bytes, what: str = "PDF") -> List[str]:
    """Each page as a base64 JPEG, for the vision model. Needs no text layer,
    so scanned papers work too (as well as the scan is legible)."""
    _check_pdf_bytes(pdf_bytes, what)
    try:
        doc = pdfium.PdfDocument(pdf_bytes)
    except pdfium.PdfiumError as e:
        if "password" in str(e).lower():
            raise ImportProblem(f"The {what} is password-protected. Remove the password and try again.")
        raise ImportProblem(f"The {what} couldn't be read. Try re-saving it as PDF.")
    try:
        if len(doc) > MAX_PAGES:
            raise ImportProblem(f"The {what} has {len(doc)} pages — split it into files of up to {MAX_PAGES} pages.")
        images = []
        for i in range(len(doc)):
            img = doc[i].render(scale=RENDER_SCALE).to_pil().convert("RGB")
            img.thumbnail((MAX_RENDER_SIDE, MAX_RENDER_SIDE))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=82, optimize=True)
            images.append(base64.b64encode(buf.getvalue()).decode("ascii"))
        return images
    finally:
        doc.close()


def image_parts(images: List[str], label: str) -> List[Dict[str, str]]:
    """One part per page: Groq allows ~8,000 tokens/minute and an image alone is 2,048."""
    return [{"label": f"{label} · page {n}", "image": img} for n, img in enumerate(images, 1)]


def extract_pages(pdf_bytes: bytes, what: str = "PDF") -> List[str]:
    _check_pdf_bytes(pdf_bytes, what)
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        # Many "protected" PDFs only restrict editing and open with an empty
        # password; decrypt() reports failure by returning 0, not by raising.
        if reader.is_encrypted:
            try:
                opened = reader.decrypt("")
            except Exception:
                opened = 0
            if not opened:
                raise ImportProblem(f"The {what} is password-protected. Remove the password and try again.")
        if len(reader.pages) > MAX_PAGES:
            raise ImportProblem(f"The {what} has {len(reader.pages)} pages — split it into files of up to {MAX_PAGES} pages.")
        pages = [(p.extract_text() or "").strip() for p in reader.pages]
    except ImportProblem:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError) as e:
        raise ImportProblem(f"The {what} couldn't be read ({e.__class__.__name__}). Try re-saving it as PDF.")
    # Scanned PDFs yield no text (at most a stray page number); a genuine
    # answer key can be as short as "1. (b)", so the bar is deliberately low.
    if sum(len(re.sub(r"\s", "", p)) for p in pages) < 5:
        raise ImportProblem(
            f"No text could be read from the {what} — it looks scanned or photographed. "
            "Only typed PDFs (where you can select the text) are supported."
        )
    return pages


_QUESTION_START = re.compile(r"^\s*(?:Q\.?\s*)?\d{1,3}\s*[\.\)]\s+\S")


def _split_long_page(text: str, budget: int) -> List[str]:
    """Split a page that alone exceeds the budget, preferring to cut just
    before a numbered question so no question is torn in half."""
    pieces, current = [], []
    size = 0
    for line in text.splitlines():
        if size + len(line) > budget and current:
            # Walk back to the last question start in this piece, if any.
            cut = next((i for i in range(len(current) - 1, 0, -1) if _QUESTION_START.match(current[i])), None)
            if cut:
                pieces.append("\n".join(current[:cut]))
                current = current[cut:]
            else:
                pieces.append("\n".join(current))
                current = []
            size = sum(len(l) + 1 for l in current)
        current.append(line)
        size += len(line) + 1
    if current:
        pieces.append("\n".join(current))
    return [p for p in pieces if p.strip()]


def chunk_pages(pages: List[str], label: str, budget: int = CHUNK_CHARS) -> List[Dict[str, str]]:
    """Group pages into parts of at most `budget` characters, in page order.

    Pages are joined as continuous text, with no "page N" markers: with
    markers the model treated questions after a page break as a fresh
    start, and dropped case sub-questions out of their case study."""
    parts: List[Dict[str, str]] = []
    buf: List[str] = []
    first = last = None

    def flush():
        nonlocal buf, first, last
        if buf:
            span = f"page {first}" if first == last else f"pages {first}–{last}"
            parts.append({"label": f"{label} · {span}", "text": "\n\n".join(buf)})
        buf, first, last = [], None, None

    for n, text in enumerate(pages, 1):
        if not text:
            continue
        block = text
        if len(block) > budget:
            flush()
            for piece in _split_long_page(text, budget):
                parts.append({"label": f"{label} · page {n}", "text": piece})
            continue
        if buf and sum(len(b) + 2 for b in buf) + len(block) > budget:
            flush()
        buf.append(block)
        first = n if first is None else first
        last = n
    flush()
    return parts


# ─── Groq ─────────────────────────────────────────────────────────────────────

_PROMPT_BODY = """Return ONE JSON object and nothing else:
{
  "title": the paper title from its heading, or null,
  "level": "FINAL" | "INTERMEDIATE" | "FOUNDATION" | null,
  "subject": the subject name as written, or null,
  "duration_minutes": number or null,
  "total_marks": number or null,
  "sections": [ { "title": the section heading or null, "questions": [ {
      "number": the question number as printed (integer), or null,
      "type": "normal" or "case",
      "case_narrative": the full case passage, ONLY on the first question of each case (omit otherwise),
      "content": the question text without its number,
      "options": the option texts without their (a)/(b)/(c)/(d) labels,
      "answer_line": the answer exactly as printed with this question (e.g. "Answer: (b)"), or null if none is printed with it,
      "correct_option": 0-based index of that printed answer (a=0, b=1, c=2, d=3), or null — always null when answer_line is null,
      "explanation": the explanation if the paper gives one, else "",
      "marks": number or null,
      "negative_marks": number or null
  } ] } ],
  "answer_key": [ { "number": question number, "answer": "a" | "b" | "c" | "d" } ],
  "continuation": null, or — only when this part BEGINS with the rest of a question or case passage from the previous part —
    { "number": that question's number, "content": more of its question text or "", "options": its remaining options (without labels),
      "answer_line": its answer as printed or null, "explanation": its explanation or "", "case_narrative": more of the case passage or "" }
}
Rules:
- Include every question in this part, in order. Never skip, merge or invent questions.
- Answers come ONLY from what is printed. You are copying the paper, not sitting it: never solve a question or fill in an answer you know, even an obvious one. An answer printed with its question goes in answer_line and correct_option. Answers listed separately (an answer key or answer table) go in answer_key: copy EVERY entry of the key exactly as printed, including entries for question numbers that are not in this part — those questions are in another part of the paper.
- If this part is only an answer key, return an empty "sections" list and fill "answer_key".
- Copy question and option text exactly, keeping symbols such as ₹ and %. Ignore page headers, footers and page numbers.
- A case study is a passage followed by its questions. Every question after a case passage belongs to that case — including questions after a page break — until the next case passage, a new section heading, or the answer key. All of them are type "case"; only the first carries case_narrative. A question that continues a case whose passage is not in this part is also type "case".
- marks and negative_marks: use what the paper states (e.g. "each MCQ carries 2 marks"); null if it doesn't say.
Maths: write it as plain text with Unicode symbols, exactly as printed:
- fractions as numerator/denominator, numerator first: 1/2, 5/12, (2a + b)/(a + 2b)
- powers with superscripts: x², x³, xⁿ; longer exponents as x^(n+1)
- log bases and other subscripts: log₂, log₁₀, x₁; longer ones as log_(a+b)
- a bar over a letter (complement, mean) as the letter followed by U+0304: Ā, B̄, x̄
- symbols as themselves: ∩ ∪ ∈ ∉ ⊂ ∅ √ ∛ π θ Σ ∫ ≤ ≥ ≠ ≈ ± × ÷ ∞ °; roots as √8 or √(x + 1)"""

TEXT_SYSTEM_PROMPT = (
    "You convert CA exam MCQ papers into JSON. You are given the text of one part of a paper "
    "(possibly all of it); process just what is in it.\n" + _PROMPT_BODY
)
IMAGE_SYSTEM_PROMPT = (
    "You read one page image of a CA exam MCQ paper and convert it into JSON, reading maths and "
    "symbols exactly as they appear on the page. The paper may continue on other pages; process "
    "just this page.\n" + _PROMPT_BODY
)


MAX_CARRY_CHARS = 1500


def _questions_of(result: Dict[str, Any]) -> List[dict]:
    return [q for s in (result.get("sections") or []) if isinstance(s, dict)
            for q in (s.get("questions") or []) if isinstance(q, dict)]


def _carry_dict(carry: Any) -> Dict[str, Any]:
    """The carry the browser hands back between parts. A plain string is the
    older form (just a case passage), still accepted from open tabs."""
    if isinstance(carry, str):
        carry = {"case": carry}
    if not isinstance(carry, dict):
        carry = {}
    number = _num(carry.get("last_number"))
    return {
        "case": _text(carry.get("case"))[:MAX_CARRY_CHARS] or None,
        "last_number": int(number) if number is not None and number == int(number) else None,
        "last_unanswered": bool(carry.get("last_unanswered")),
    }


def next_carry(result: Dict[str, Any], incoming: Any) -> Optional[Dict[str, Any]]:
    """What the next part needs to know about where this one stopped:
    - case: the passage of a case study this part ended inside, so the next
      part's opening questions stay in that case;
    - last_number / last_unanswered: the last question seen and whether its
      answer was on this part — an "Answer: (b)" line pushed onto the next
      page by a page break is then credited to the right question, and the
      next page numbers on from it instead of restarting."""
    prev = _carry_dict(incoming)
    questions = _questions_of(result)
    if not questions:
        return prev if any(prev.values()) else None  # e.g. a page of instructions only
    last = questions[-1]
    case = None
    if _text(last.get("type")).lower() == "case":
        case = prev["case"]
        for q in reversed(questions):
            if _text(q.get("type")).lower() != "case":
                break
            if _text(q.get("case_narrative")):
                case = _text(q.get("case_narrative"))[:MAX_CARRY_CHARS]
                break
    number = _num(last.get("number"))
    return {
        "case": case,
        "last_number": int(number) if number is not None and number == int(number) else None,
        "last_unanswered": last.get("correct_option") is None,
    }


def _context_text(carry: Any) -> str:
    c = _carry_dict(carry)
    lines = []
    if c["case"]:
        lines.append(
            "The previous part of this paper ended in the middle of a case study. Its passage was:\n"
            f'"""{c["case"]}"""\n'
            'Questions at the start of this part that continue that case are type "case" - '
            "leave their case_narrative empty, the passage is already recorded."
        )
    if c["last_number"] is not None:
        n = c["last_number"]
        lines.append(
            f"The previous part ended with question {n}; questions here continue from {n + 1} — use the numbers as printed. "
            f"A page break can split question {n}: if this part begins with the rest of it (more of its text, its remaining "
            f"options, its answer line or explanation), put that in \"continuation\" with number {n} — do not start a new question for it."
        )
    if c["case"]:
        lines.append('If this part begins with more of that case passage (before any question), put that text in continuation.case_narrative.')
    return "CONTEXT:\n" + "\n".join(lines) + "\n\n" if lines else ""


_ANSWER_LETTER = re.compile(r"\(\s*([a-dA-D])\s*\)|\b(?:ans(?:wer)?|option|correct)\b\s*[:.\-–]?\s*\(?\s*([a-dA-D])\b", re.IGNORECASE)
GUESSED_ANSWER = "The AI suggested an answer that isn't printed in the paper — pick the correct option."


def enforce_printed_answers(result: Dict[str, Any]) -> Dict[str, Any]:
    """An answer counts only if the model also copied the line it's printed
    on — and the letter is read from that copy here, not taken on trust.
    A model that "helpfully" solved an unanswered question (seen with the
    vision model) leaves no printed line behind, so its answer is dropped
    and the question flagged instead of going in silently."""
    for q in _questions_of(result):
        line = _text(q.get("answer_line"))
        if line:
            m = _ANSWER_LETTER.search(line)
            if m:
                q["correct_option"] = "abcd".index((m.group(1) or m.group(2)).lower())
        elif q.get("correct_option") is not None:
            q["correct_option"] = None
            q["import_note"] = GUESSED_ANSWER
    return result


async def convert_part(text: Optional[str], api_key: str, client: Optional[httpx.AsyncClient] = None,
                       case_context: Any = None, image: Optional[str] = None) -> Dict[str, Any]:
    """One Groq request for one part of a paper: its text, or (image=base64
    JPEG) one rendered page for the vision model. Raises AIRateLimited on a
    429 (the caller retries after the wait) and AIUnavailable otherwise.
    case_context: the previous part's carry (see next_carry)."""
    if (text is None) == (image is None):
        raise ValueError("convert_part needs exactly one of text or image")
    context = _context_text(case_context)
    if image is not None:
        payload = {
            "model": GROQ_VISION_MODEL,
            "temperature": 0,
            "max_completion_tokens": 3500,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": IMAGE_SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": context + "PAGE IMAGE:"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}},
                ]},
            ],
        }
    else:
        payload = {
            "model": GROQ_MODEL,
            "temperature": 0,
            "reasoning_effort": "medium",
            "max_completion_tokens": 5000,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": TEXT_SYSTEM_PROMPT},
                {"role": "user", "content": context + "PAPER TEXT:\n\n" + text},
            ],
        }
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=90) as c:
                res = await c.post(GROQ_URL, json=payload, headers=headers)
        else:
            res = await client.post(GROQ_URL, json=payload, headers=headers)
    except httpx.HTTPError as e:
        raise AIUnavailable(f"Couldn't reach the AI service ({e.__class__.__name__}).")
    if res.status_code == 429:
        try:
            wait = float(res.headers.get("retry-after", "20"))
        except ValueError:
            wait = 20.0
        raise AIRateLimited(max(1.0, min(wait, 120.0)))
    if res.status_code != 200:
        raise AIUnavailable(f"The AI service returned an error (HTTP {res.status_code}).")
    try:
        content = res.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
    except (KeyError, IndexError, TypeError, ValueError):
        raise AIUnavailable("The AI returned an unreadable answer for this part.")
    if not isinstance(data, dict):
        raise AIUnavailable("The AI returned an unexpected answer for this part.")
    return enforce_printed_answers(data)


# ─── Normalisation (shared by PDF and JSON) ───────────────────────────────────

_LABEL = re.compile(r"^\s*(?:\(?[a-dA-D]\)|[a-dA-D][\.\):]|option\s+[a-dA-D][\.\):]?)\s+", re.IGNORECASE)
_NUMBER_PREFIX = re.compile(r"^\s*(?:Q(?:uestion)?\.?\s*)?\(?\d{1,3}[\.\):]\s*", re.IGNORECASE)
_LETTER = re.compile(r"^\s*(?:option\s*)?\(?([a-dA-D])\)?\s*[\.\):]?\s*$", re.IGNORECASE)


def _text(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def _first(d: dict, *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _options(q: dict) -> List[str]:
    raw = _first(q, "options", "choices")
    if isinstance(raw, dict):  # {"a": "...", "b": "..."} or {"A": ...}
        raw = [raw[k] for k in sorted(raw, key=lambda k: str(k).lower())]
    if not isinstance(raw, list):  # option_a / optionA / a ... d as separate fields
        raw = []
        for letter in "abcd":
            v = _first(q, f"option_{letter}", f"option{letter.upper()}", f"option_{letter.upper()}", letter, letter.upper())
            if v is not None:
                raw.append(v)
    out = [_LABEL.sub("", o).strip() if isinstance(o, str) else str(o) for o in raw if o is not None]
    while out and not out[-1]:
        out.pop()
    return out


def _letter_index(v: Any, options: List[str]) -> Optional[int]:
    if isinstance(v, str):
        m = _LETTER.match(v)
        if m:
            return "abcd".index(m.group(1).lower())
        for i, o in enumerate(options):  # the answer written out as the option's text
            if v.strip().lower() == o.strip().lower():
                return i
    return None


def _answer(q: dict, options: List[str]) -> Tuple[Optional[int], Optional[str]]:
    """Returns (0-based index or None, a review note if the answer was present but unusable)."""
    n = len(options)
    for key in ("correct_option", "correctOptionIndex"):  # documented 0-based fields
        if key in q and q[key] is not None:
            v = q[key]
            idx = _letter_index(v, options) if isinstance(v, str) and not v.strip().isdigit() else None
            if idx is None:
                num = _num(v)
                idx = int(num) if num is not None and num == int(num) else None
            if idx is not None and 0 <= idx < n:
                return idx, None
            return None, f"Answer '{v}' doesn't match any option — pick the correct option."
    for key in ("answer", "correct_answer", "correctAnswer", "correct", "ans"):
        if key in q and q[key] not in (None, ""):
            v = q[key]
            # A bare number is checked before matching option text: with
            # options like 3/4/5/6, "5" could be that option, the 5th, or
            # index 5 — so it's flagged rather than picked.
            if _num(v) is not None:
                return None, f"Answer given as the number '{v}' — it isn't clear which option that means, so pick the correct option."
            idx = _letter_index(v, options)
            if idx is not None and idx < n:
                return idx, None
            return None, f"Answer '{v}' doesn't match any option — pick the correct option."
    return None, None


def _level(v: Any) -> Optional[str]:
    s = _text(v).upper()
    if not s:
        return None
    if "FOUND" in s:
        return "FOUNDATION"
    if "INTER" in s:
        return "INTERMEDIATE"
    if "FINAL" in s:
        return "FINAL"
    return None


def _sections_of(part: Any) -> Tuple[List[dict], dict]:
    """Accepts the shapes people (and AIs) actually produce:
    {sections: [...]}, a list of sections, a list of questions, or
    {questions: [...]}. Returns (sections, part-level metadata)."""
    def looks_like_question(x):
        # By key, not value: one question with blank text must not make the
        # whole file unreadable — it's kept and flagged (or dropped if empty).
        return isinstance(x, dict) and any(k in x for k in ("content", "question", "text", "question_text", "options"))

    if isinstance(part, dict):
        if isinstance(part.get("sections"), list):
            return part["sections"], part
        if isinstance(part.get("questions"), list):
            return [{"title": part.get("section") or None, "questions": part["questions"]}], part
        if isinstance(part.get("answer_key"), (list, dict)):
            return [], part
        if looks_like_question(part):
            return [{"title": None, "questions": [part]}], {}
    if isinstance(part, list):
        if all(isinstance(x, dict) and isinstance(x.get("questions"), list) for x in part) and part:
            return part, {}
        if all(looks_like_question(x) for x in part) and part:
            return [{"title": None, "questions": part}], {}
        if not part:
            return [], {}
    raise ImportProblem(
        "This file isn't in a format I can read. Use a list of sections, each with a \"title\" and a "
        "\"questions\" list (see mcq_upload_guide.md), or a plain list of questions."
    )


def _answer_key(part: Any) -> Dict[int, str]:
    if not isinstance(part, dict):
        return {}
    raw = part.get("answer_key")
    key: Dict[int, str] = {}
    if isinstance(raw, dict):
        raw = [{"number": k, "answer": v} for k, v in raw.items()]
    if isinstance(raw, list):
        for e in raw:
            if isinstance(e, dict):
                n = _num(e.get("number", e.get("question")))
                a = e.get("answer", e.get("option"))
                if n is not None and isinstance(a, str):
                    key[int(n)] = a
    return key


def _clean_question(q: dict) -> Optional[dict]:
    content = _NUMBER_PREFIX.sub("", _text(_first(q, "content", "question", "text", "question_text")) or "").strip()
    options = _options(q)
    if not content and not options:
        return None  # nothing usable
    correct, answer_note = _answer(q, options)
    if correct is None and not answer_note:
        # e.g. GUESSED_ANSWER from enforce_printed_answers, said more precisely than NO_ANSWER
        answer_note = _text(q.get("import_note")) or None
    narrative = _text(_first(q, "case_narrative", "caseText", "case_text", "passage", "case_passage"))
    is_case = _text(q.get("type")).lower() == "case" or bool(narrative)
    marks = _num(q.get("marks"))
    neg = _num(_first(q, "negative_marks", "negativeMarks"))
    difficulty = _text(q.get("difficulty")).lower()
    number = _num(_first(q, "number", "question_number", "qno"))
    return {
        "type": "case" if is_case else "normal",
        "case_narrative": narrative,
        "content": content,
        "options": options,
        "correct_option": correct,
        "explanation": _text(_first(q, "explanation", "solution", "reason")),
        # None = not stated; filled from the rest of the paper in normalize_import.
        "marks": marks if marks is not None and marks >= 0 else None,
        "negative_marks": neg if neg is not None and neg >= 0 else None,
        "difficulty": difficulty if difficulty in DIFFICULTIES else "medium",
        "_number": int(number) if number is not None and number == int(number) else None,
        "_answer_note": answer_note,
    }


def _apply_continuation(cont: Any, sections: List[dict]) -> None:
    """Join the start of a part back onto the question (or case passage) a
    page break cut off at the end of the previous part: more question text,
    the remaining options, its printed answer, its explanation."""
    if not isinstance(cont, dict):
        return
    earlier = [q for s in sections for q in s["questions"]]
    if not earlier:
        return
    target = earlier[-1]
    n = _num(cont.get("number"))
    if n is not None:
        same = [q for q in earlier if q["_number"] == n]
        if same:
            target = same[-1]
    more = _text(cont.get("content"))
    if more:
        target["content"] = f"{target['content']} {more}".strip()
    options = cont.get("options") if isinstance(cont.get("options"), list) else []
    target["options"] = target["options"] + [_LABEL.sub("", o).strip() for o in options if isinstance(o, str) and o.strip()]
    if not target["explanation"]:
        target["explanation"] = _text(cont.get("explanation"))
    line = _text(cont.get("answer_line"))
    if line and target["correct_option"] is None:
        m = _ANSWER_LETTER.search(line)
        if m:
            target["correct_option"] = "abcd".index((m.group(1) or m.group(2)).lower())
            target["_answer_note"] = None
    passage = _text(cont.get("case_narrative"))
    if passage:
        heads = [q for q in earlier if q["type"] == "case" and q["case_narrative"]]
        if heads:
            heads[-1]["case_narrative"] = f"{heads[-1]['case_narrative']} {passage}"


def normalize_import(parts: List[Any]) -> dict:
    """Merges one or more parts (AI outputs for consecutive chunks of a paper,
    or a single uploaded JSON document) into the editor's shape."""
    if not isinstance(parts, list) or not parts:
        raise ImportProblem("Nothing to import.")

    meta: Dict[str, Any] = {"title": None, "level": None, "subject": None, "duration_minutes": None, "total_marks": None}
    sections: List[dict] = []
    key: Dict[int, str] = {}

    for part in parts:
        part_sections, part_meta = _sections_of(part)
        for field, aliases in (("title", ("title", "paper_title")), ("subject", ("subject",)),
                               ("duration_minutes", ("duration_minutes", "durationMinutes", "duration")),
                               ("total_marks", ("total_marks", "totalMarks", "marks"))):
            if meta[field] is None:
                v = _first(part_meta, *aliases) if isinstance(part_meta, dict) else None
                if field in ("duration_minutes", "total_marks"):
                    v = _num(v) if not isinstance(v, (list, dict)) else None
                    v = v if v and v > 0 else None
                elif not isinstance(v, str):
                    v = None
                meta[field] = v.strip() if isinstance(v, str) else v
        if meta["level"] is None and isinstance(part_meta, dict):
            meta["level"] = _level(part_meta.get("level"))
        key.update(_answer_key(part))
        _apply_continuation(part.get("continuation") if isinstance(part, dict) else None, sections)

        for i, s in enumerate(part_sections):
            if not isinstance(s, dict):
                continue
            title = _text(s.get("title"))
            qs = [c for c in (_clean_question(q) for q in (s.get("questions") or []) if isinstance(q, dict)) if c]
            if not qs:
                continue
            # A section that carries on across a part boundary (untitled, or
            # same heading as the previous one) continues that section.
            if i == 0 and sections and (not title or title.lower() == sections[-1]["title"].lower()):
                sections[-1]["questions"].extend(qs)
            else:
                sections.append({"title": title or f"Section {chr(65 + len(sections) % 26)}", "questions": qs})

    all_qs = [q for s in sections for q in s["questions"]]
    if not all_qs:
        raise ImportProblem("No questions were found in the file.")

    # "Each question carries 2 marks" is usually printed once, on page 1, so
    # questions in later parts come back with marks unstated. Give those the
    # paper's most common stated value rather than a flat default.
    for field, fallback in (("marks", 1.0), ("negative_marks", 0.0)):
        stated = [q[field] for q in all_qs if q[field] is not None]
        prevailing = max(set(stated), key=stated.count) if stated else fallback
        for q in all_qs:
            if q[field] is None:
                q[field] = prevailing

    # Answers listed separately (an answer key / answer table), by number.
    issues: List[str] = []
    if key:
        numbers = [q["_number"] for q in all_qs]
        unique = all(n is not None for n in numbers) and len(set(numbers)) == len(numbers)
        if unique:
            by_number = {q["_number"]: q for q in all_qs}
            for n, letter in key.items():
                q = by_number.get(n)
                if q is None:
                    issues.append(f"The answer key lists question {n}, which wasn't found.")
                elif q["correct_option"] is None:
                    idx = _letter_index(letter, q["options"])
                    if idx is not None and idx < len(q["options"]):
                        q["correct_option"] = idx
        elif len(key) == len(all_qs):
            # Numbering restarts per section, but the key covers every question: apply in order.
            for q, n in zip(all_qs, sorted(key)):
                if q["correct_option"] is None:
                    idx = _letter_index(key[n], q["options"])
                    if idx is not None and idx < len(q["options"]):
                        q["correct_option"] = idx
        else:
            issues.append("The answer key couldn't be matched to the questions (question numbers repeat) — pick answers by hand.")

    # The editor groups a case study as a run of consecutive "case" questions
    # within a section, so two case studies back to back would merge into one
    # sharing the first passage. Give every further case study its own section.
    split: List[dict] = []
    for s in sections:
        current = {"title": s["title"], "questions": []}
        case_no = 1
        for q in s["questions"]:
            prev = current["questions"][-1] if current["questions"] else None
            if q["type"] == "case" and q["case_narrative"] and prev is not None and prev["type"] == "case":
                split.append(current)
                case_no += 1
                current = {"title": f"{s['title']} — Case {case_no}", "questions": []}
            current["questions"].append(q)
        split.append(current)

    flagged = answered = 0
    out_sections = []
    for s in split:
        out_qs = []
        for i, q in enumerate(s["questions"]):
            review: List[str] = []
            co = q["correct_option"]
            if co is not None and not (0 <= co < len(q["options"])):
                # e.g. "Answer: (b)" for a question whose other options were lost
                q["correct_option"] = None
                q["_answer_note"] = "The answer given doesn't match one of the options found — check the options and pick the answer."
            if q["correct_option"] is None:
                review.append(q["_answer_note"] or NO_ANSWER)
            else:
                answered += 1
            if not q["content"]:
                review.append("Question text is missing.")
            if len(q["options"]) < 2:
                review.append("Needs at least 2 options.")
            elif len(q["options"]) < 4:
                review.append(f"Only {len(q['options'])} options were found — check them against the paper.")
            if any(not o for o in q["options"]):
                review.append("One of the options is blank.")
            is_head = q["type"] == "case" and (i == 0 or s["questions"][i - 1]["type"] != "case")
            if is_head and not q["case_narrative"]:
                review.append("Case question without its passage — add the case passage.")
            if review:
                flagged += 1
            out_qs.append({k: v for k, v in q.items() if not k.startswith("_")} | {"review": review})
        out_sections.append({"title": s["title"], "questions": out_qs})

    return {
        "meta": meta,
        "sections": out_sections,
        "issues": issues,
        "stats": {"questions": len(all_qs), "answered": answered, "flagged": flagged, "sections": len(out_sections)},
    }
