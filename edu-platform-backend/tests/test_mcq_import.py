"""MCQ import: PDF text extraction and splitting, the Groq call (mocked — no
network), the shared normalisation used by both PDF and JSON imports, and
the endpoints' access rules.

normalize_import is where correctness lives: answers are never guessed or
defaulted, answer keys are matched by number across parts, every case study
stays whole and separate, and anything uncertain is flagged for review.
"""
import asyncio
import base64
import io
import json

import httpx
import pytest
from pypdf import PdfWriter

from app.core import mcq_import as core
from app.core.mcq_import import (
    GROQ_VISION_MODEL, IMAGE_SYSTEM_PROMPT, NO_ANSWER, TEXT_SYSTEM_PROMPT, AIRateLimited, AIUnavailable, ImportProblem,
    GUESSED_ANSWER, chunk_pages, convert_part, enforce_printed_answers, extract_pages, next_carry,
    normalize_import, render_pages,
)

ADMIN = {"id": "admin-1", "role": "admin", "email": "a@x.com"}
EDITOR = {"id": "editor-1", "role": "mcq_editor", "email": "e@x.com"}
STUDENT = {"id": "student-1", "role": "student", "email": "s@x.com"}
MENTOR = {"id": "mentor-1", "role": "mentor", "email": "m@x.com"}


def text_pdf(*pages: str) -> bytes:
    """A minimal valid PDF whose pages contain the given (ASCII) text."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        lines = text.split("\n")
        ops = "BT /F1 11 Tf 14 TL 50 780 Td " + " ".join(
            f"({l.replace(chr(92), chr(92) * 2).replace('(', chr(92) + '(').replace(')', chr(92) + ')')}) Tj T*" for l in lines) + " ET"
        objs.append(f"<< /Length {len(ops)} >>\nstream\n{ops}\nendstream")
        content_ref = len(objs)
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_ref} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for o in offsets:
        out.write(f"{o:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


PAPER = "CA FINAL - PAPER 1: FINANCIAL REPORTING\n1. Under Ind AS 2, inventories are measured at:\n(a) Fair value\n(b) Lower of cost and NRV"


# ─── PDF text ────────────────────────────────────────────────────────────────

def test_extracts_text_from_a_typed_pdf():
    pages = extract_pages(text_pdf(PAPER, "2. Second page question?\n(a) Yes\n(b) No"))
    assert len(pages) == 2
    assert "Ind AS 2" in pages[0] and "Second page" in pages[1]


@pytest.mark.parametrize("data,message", [
    (b"", "empty"),
    (b"hello, I am not a PDF", "isn't a PDF"),
    (b"%PDF-1.4 garbage that is not really a pdf", "couldn't be read"),
])
def test_rejects_bad_files_with_a_clear_reason(data, message):
    with pytest.raises(ImportProblem, match=message):
        extract_pages(data)


def test_scanned_pdf_with_no_text_is_rejected_with_explanation():
    w = PdfWriter()
    w.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(ImportProblem, match="scanned"):
        extract_pages(buf.getvalue())


def test_password_protected_pdf_is_rejected_with_explanation():
    w = PdfWriter()
    w.add_blank_page(width=612, height=792)
    w.encrypt(user_password="secret", owner_password="owner")
    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(ImportProblem, match="password"):
        extract_pages(buf.getvalue())


def test_oversized_pdf_is_rejected(monkeypatch):
    monkeypatch.setattr(core, "MAX_PDF_BYTES", 100)
    with pytest.raises(ImportProblem, match="over"):
        extract_pages(text_pdf(PAPER))


# ─── Splitting into parts ────────────────────────────────────────────────────

def test_pages_are_grouped_into_parts_under_budget_in_order():
    pages = ["a" * 400, "b" * 400, "", "c" * 400]
    parts = chunk_pages(pages, "Paper", budget=900)
    assert [p["label"] for p in parts] == ["Paper · pages 1–2", "Paper · page 4"]
    assert all(len(p["text"]) <= 900 for p in parts)
    assert "Page" not in parts[0]["text"]  # no page markers: they broke case studies across pages


def test_a_page_over_budget_is_cut_just_before_a_question():
    page = "\n".join(f"{n}. Question number {n} text\n(a) one\n(b) two\n(c) three\n(d) four" for n in range(1, 21))
    parts = chunk_pages([page], "Paper", budget=300)
    assert len(parts) > 1
    for p in parts:
        assert len(p["text"]) <= 300
        assert p["text"].lstrip()[0].isdigit()  # every part starts at a question, none torn mid-way
    rejoined = "\n".join(p["text"] for p in parts)
    assert all(f"{n}. Question number {n} " in rejoined for n in range(1, 21))


# ─── Normalisation: formats ──────────────────────────────────────────────────

def q(content="What is 2 + 2?", options=("3", "4", "5", "6"), **extra):
    return {"content": content, "options": list(options), **extra}


def only_q(result):
    return result["sections"][0]["questions"][0]


def test_documented_list_of_sections_format():
    r = normalize_import([[{"title": "Section A", "questions": [q(correct_option=1)]}]])
    assert r["sections"][0]["title"] == "Section A"
    assert only_q(r)["correct_option"] == 1 and only_q(r)["review"] == []


@pytest.mark.parametrize("doc", [
    {"sections": [{"title": "Section A", "questions": [q(correct_option=1)]}]},  # wrapped (AI / import output)
    [q(correct_option=1)],                                                       # bare list of questions
    {"questions": [q(correct_option=1)]},                                        # single object with questions
])
def test_other_common_shapes_are_accepted(doc):
    assert only_q(normalize_import([doc]))["correct_option"] == 1


@pytest.mark.parametrize("doc", [{"hello": "world"}, "just text", [1, 2, 3], {"sections": []}])
def test_unreadable_or_empty_files_explain_why(doc):
    with pytest.raises(ImportProblem):
        normalize_import([doc])


@pytest.mark.parametrize("answer,expected", [
    ({"answer": "b"}, 1), ({"answer": "(c)"}, 2), ({"answer": "D"}, 3), ({"answer": "Option A"}, 0),
    ({"correct_answer": "b)"}, 1), ({"answer": "5"}, None), ({"correct": "4"}, None),
    ({"answer": "Five"}, None), ({"correct_option": "c"}, 2), ({"correctOptionIndex": 3}, 3),
])
def test_answers_written_as_letters_or_option_text(answer, expected):
    got = only_q(normalize_import([[q(**answer)]]))["correct_option"]
    # "5" / "4" under "answer" are ambiguous (0- or 1-based?), so never guessed.
    if answer in ({"answer": "5"}, {"correct": "4"}):
        assert got is None
    else:
        assert got == expected


def test_answer_written_as_the_option_text():
    assert only_q(normalize_import([[q(answer="4")]]))["correct_option"] is None  # "4" is ambiguous as a number
    assert only_q(normalize_import([[q(options=("Ind AS 2", "Ind AS 16"), answer="Ind AS 16")]]))["correct_option"] == 1


def test_a_missing_answer_is_left_unset_and_flagged_never_defaulted_to_a():
    item = only_q(normalize_import([[q()]]))
    assert item["correct_option"] is None  # the old uploader silently made this 0 (option A)
    assert item["review"] == [NO_ANSWER]


@pytest.mark.parametrize("bad", [{"correct_option": 7}, {"correct_option": -1}, {"answer": 2}])
def test_unusable_answers_are_flagged_with_a_reason(bad):
    item = only_q(normalize_import([[q(**bad)]]))
    assert item["correct_option"] is None
    assert item["review"] and "pick the correct option" in item["review"][0]


def test_option_labels_and_question_numbers_are_stripped():
    item = only_q(normalize_import([[{"question": "Q12. Which is right?", "options": ["(a) One", "b) Two", "C. Three", "Option D: Four"], "answer": "a"}]]))
    assert item["content"] == "Which is right?"
    assert item["options"] == ["One", "Two", "Three", "Four"]


def test_options_given_as_an_object_or_separate_fields():
    a = only_q(normalize_import([[{"question": "Q?", "options": {"a": "One", "b": "Two", "c": "Three", "d": "Four"}, "answer": "d"}]]))
    b = only_q(normalize_import([[{"question": "Q?", "option_a": "One", "option_b": "Two", "option_c": "Three", "option_d": "Four", "answer": "b"}]]))
    assert a["options"] == b["options"] == ["One", "Two", "Three", "Four"]
    assert (a["correct_option"], b["correct_option"]) == (3, 1)


def test_suspicious_questions_are_flagged():
    r = normalize_import([[q(options=("one", "two", "three"), correct_option=0), q(options=("one",), correct_option=0),
                           q(content="", correct_option=0), q(options=("one", "", "three", "four"), correct_option=0)]])
    reviews = [x["review"] for x in r["sections"][0]["questions"]]
    assert "Only 3 options" in reviews[0][0]
    assert any("at least 2 options" in m for m in reviews[1])
    assert any("text is missing" in m for m in reviews[2])
    assert any("options is blank" in m for m in reviews[3])
    assert r["stats"]["flagged"] == 4


def test_junk_entries_with_no_text_and_no_options_are_dropped():
    r = normalize_import([[q(correct_option=0), {"content": "", "options": []}]])
    assert r["stats"]["questions"] == 1


# ─── Normalisation: answer keys across parts ─────────────────────────────────

def part(questions, title=None, key=None, **meta):
    out = {"sections": [{"title": title, "questions": questions}] if questions else [], **meta}
    if key is not None:
        out["answer_key"] = key
    return out


def test_answer_key_in_a_later_part_fills_answers_by_number():
    parts = [
        part([q(number=1), q(number=2)], title="Part A"),
        part([q(number=3)]),
        part([], key=[{"number": 1, "answer": "c"}, {"number": 2, "answer": "a"}, {"number": 3, "answer": "d"}]),
    ]
    r = normalize_import(parts)
    assert [x["correct_option"] for s in r["sections"] for x in s["questions"]] == [2, 0, 3]
    assert r["stats"]["answered"] == 3


def test_answer_key_does_not_override_an_answer_printed_with_the_question():
    r = normalize_import([part([q(number=1, correct_option=1)], key=[{"number": 1, "answer": "d"}])])
    assert only_q(r)["correct_option"] == 1


def test_answer_key_entry_for_a_missing_question_is_reported():
    r = normalize_import([part([q(number=1)], key=[{"number": 1, "answer": "a"}, {"number": 9, "answer": "b"}])])
    assert any("question 9" in i for i in r["issues"])


def test_restarted_numbering_with_a_complete_key_is_applied_in_order():
    parts = [part([q(number=1), q(number=2)], title="Part A"), part([q(number=1)], title="Part B"),
             part([], key={"1": "b", "2": "c", "3": "d"})]
    r = normalize_import(parts)
    assert [x["correct_option"] for s in r["sections"] for x in s["questions"]] == [1, 2, 3]


def test_restarted_numbering_with_a_partial_key_is_not_guessed():
    parts = [part([q(number=1), q(number=2)], title="Part A"), part([q(number=1)], title="Part B"), part([], key={"1": "b"})]
    r = normalize_import(parts)
    assert all(x["correct_option"] is None for s in r["sections"] for x in s["questions"])
    assert r["issues"]


# ─── Normalisation: case studies ─────────────────────────────────────────────

def case(narrative="", **kw):
    return q(type="case", case_narrative=narrative, correct_option=0, **kw)


def test_back_to_back_case_studies_each_get_their_own_section():
    r = normalize_import([part([q(correct_option=0), case("Case one passage"), case(), case("Case two passage"), case()], title="Part B")])
    secs = r["sections"]
    assert [s["title"] for s in secs] == ["Part B", "Part B — Case 2"]
    assert [x["type"] for x in secs[0]["questions"]] == ["normal", "case", "case"]
    assert secs[1]["questions"][0]["case_narrative"] == "Case two passage"
    assert all(not x["review"] for s in secs for x in s["questions"])


def test_case_study_split_across_parts_stays_one_case():
    parts = [part([case("Alpha Ltd passage"), case()], title="Part B"), part([case(), case()])]  # 2nd part: untitled continuation
    r = normalize_import(parts)
    assert len(r["sections"]) == 1
    qs = r["sections"][0]["questions"]
    assert [x["type"] for x in qs] == ["case"] * 4
    assert qs[0]["case_narrative"] == "Alpha Ltd passage" and all(not x["review"] for x in qs)


def test_case_question_without_any_passage_is_flagged():
    r = normalize_import([part([case()], title="Part B")])
    assert any("without its passage" in m for m in only_q(r)["review"])


def test_a_question_with_a_passage_is_a_case_even_if_type_is_missing():
    assert only_q(normalize_import([[q(passage="Some passage", correct_option=0)]]))["type"] == "case"


# ─── Normalisation: marks and paper details ──────────────────────────────────

def test_unstated_marks_take_the_papers_prevailing_value():
    r = normalize_import([part([q(marks=2, correct_option=0), q(marks=2, correct_option=0)], title="A"),
                          part([q(correct_option=0)], title="B")])
    assert [x["marks"] for s in r["sections"] for x in s["questions"]] == [2, 2, 2]


def test_marks_default_to_one_and_no_negative_when_never_stated():
    item = only_q(normalize_import([[q(correct_option=0)]]))
    assert (item["marks"], item["negative_marks"]) == (1.0, 0.0)


def test_paper_details_come_from_the_first_part_that_states_them():
    parts = [part([q(correct_option=0)], title="A", level="CA Intermediate", subject="Auditing", duration_minutes="60"),
             part([q(correct_option=0)], title="B", total_marks=28, subject="Ignored")]
    meta = normalize_import(parts)["meta"]
    assert meta == {"title": None, "level": "INTERMEDIATE", "subject": "Auditing", "duration_minutes": 60.0, "total_marks": 28.0}


# ─── Case carry-over between parts ───────────────────────────────────────────

def test_carry_is_the_passage_when_a_part_ends_inside_a_case():
    assert next_carry(part([case("Delta passage"), case()]), None)["case"] == "Delta passage"


def test_no_case_carried_when_a_part_ends_on_a_normal_question():
    assert next_carry(part([case("Delta passage"), q()]), "older")["case"] is None


def test_carry_passes_through_a_part_that_only_continues_the_case():
    assert next_carry(part([case(), case()]), "Delta passage")["case"] == "Delta passage"
    assert next_carry(part([]), "Delta passage")["case"] == "Delta passage"
    assert next_carry(part([]), None) is None


def test_carry_records_where_the_part_stopped():
    carry = next_carry(part([q(number=5, correct_option=0), q(number=6)]), None)
    assert carry == {"case": None, "last_number": 6, "last_unanswered": True}
    assert next_carry(part([q(number=7, correct_option=1)]), carry)["last_unanswered"] is False


def test_next_part_is_told_to_number_on_and_report_a_split_question():
    seen = {}

    def handler(request):
        seen["user"] = json.loads(request.content)["messages"][1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    async def go():
        async with mock_client(handler) as c:
            return await convert_part("text", "k", client=c, case_context={"case": None, "last_number": 6, "last_unanswered": True})

    run(go())
    assert "continue from 7" in seen["user"]
    assert 'put that in "continuation" with number 6' in seen["user"]


def test_a_question_split_by_a_page_break_is_joined_back_together():
    """Q6's first option ends one page; its other options, answer line and
    explanation start the next (as in a real test paper)."""
    parts = [part([q(number=5, correct_option=0, answer_line="Answer: (a)"), q(content="Depreciation for the year is:", options=("₹2,00,000",), number=6)], title="Part B"),
             {"sections": [{"title": None, "questions": [q(content="Next one?", number=7, correct_option=2)]}],
              "continuation": {"number": 6, "content": "", "options": ["(b) ₹2,10,000", "(c) ₹2,14,000", "(d) ₹2,04,000"],
                               "answer_line": "Answer: (b)", "explanation": "₹10,50,000 / 5 years.", "case_narrative": ""}}]
    qs = [x for s in normalize_import(parts)["sections"] for x in s["questions"]]
    q6 = qs[1]
    assert q6["options"] == ["₹2,00,000", "₹2,10,000", "₹2,14,000", "₹2,04,000"]
    assert (q6["correct_option"], q6["explanation"], q6["review"]) == (1, "₹10,50,000 / 5 years.", [])
    assert len(qs) == 3 and qs[2]["content"] == "Next one?"


def test_a_case_passage_split_by_a_page_break_is_joined_back_together():
    parts = [part([case("Alpha Ltd bought a machine")], title="Part B"),
             {"sections": [{"title": None, "questions": [case()]}],
              "continuation": {"number": None, "case_narrative": "for ₹10,00,000 on 1 April 2025."}}]
    qs = [x for s in normalize_import(parts)["sections"] for x in s["questions"]]
    assert qs[0]["case_narrative"] == "Alpha Ltd bought a machine for ₹10,00,000 on 1 April 2025."
    assert [x["type"] for x in qs] == ["case", "case"]


def test_an_answer_pointing_past_the_options_never_counts_as_answered():
    item = only_q(normalize_import([part([q(options=("only one",), number=6)], key=[{"number": 6, "answer": "b"}])]))
    assert item["correct_option"] is None and item["review"]


def test_an_answer_pushed_onto_the_next_part_lands_on_its_question():
    """Q6's options end one page and its "Answer: (b)" line starts the next."""
    parts = [part([q(number=5, correct_option=0), q(number=6)], title="Part A"),
             part([q(content="Next question", number=7, correct_option=2)], key=[{"number": 6, "answer": "b"}])]
    r = normalize_import(parts)
    qs = [x for s in r["sections"] for x in s["questions"]]
    assert [x["correct_option"] for x in qs] == [0, 1, 2]
    assert r["stats"]["answered"] == 3


# ─── Answers must be printed, not supplied by the AI ─────────────────────────

def test_answer_is_read_from_the_printed_line_not_taken_on_trust():
    r = enforce_printed_answers(part([q(answer_line="Answer: (c)", correct_option=0)]))
    assert r["sections"][0]["questions"][0]["correct_option"] == 2


@pytest.mark.parametrize("line,expected", [("Answer: (b)", 1), ("Ans. d", 3), ("Ans: (A)", 0), ("Correct option: c", 2), ("(d)", 3)])
def test_common_answer_line_styles(line, expected):
    assert enforce_printed_answers(part([q(answer_line=line, correct_option=None)]))["sections"][0]["questions"][0]["correct_option"] == expected


def test_an_answer_with_no_printed_line_is_dropped_and_flagged():
    r = enforce_printed_answers(part([q(correct_option=1)]))  # the AI "knew" it, the paper didn't say
    item = r["sections"][0]["questions"][0]
    assert item["correct_option"] is None and item["import_note"] == GUESSED_ANSWER
    assert only_q(normalize_import([r]))["review"] == [GUESSED_ANSWER]


def test_a_printed_line_without_a_letter_keeps_the_models_index():
    r = enforce_printed_answers(part([q(answer_line="Answer: Lower of cost and NRV", correct_option=1)]))
    assert r["sections"][0]["questions"][0]["correct_option"] == 1


# ─── The Groq call (mocked) ──────────────────────────────────────────────────

def mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run(coro):
    return asyncio.run(coro)


def test_convert_part_returns_the_models_json_and_sends_the_carry():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(part([q(correct_option=0)]))}}]})

    async def go():
        async with mock_client(handler) as c:
            return await convert_part("1. What?", "gsk_test", client=c, case_context="Delta passage")

    result = run(go())
    assert result["sections"][0]["questions"][0]["content"] == "What is 2 + 2?"
    user = seen["body"]["messages"][1]["content"]
    assert "Delta passage" in user and "continue that case" in user and user.endswith("PAPER TEXT:\n\n1. What?")
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["auth"] == "Bearer gsk_test"


def test_convert_part_without_carry_sends_just_the_text():
    seen = {}

    def handler(request):
        seen["user"] = json.loads(request.content)["messages"][1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    async def go():
        async with mock_client(handler) as c:
            return await convert_part("text", "k", client=c)

    run(go())
    assert seen["user"] == "PAPER TEXT:\n\ntext"


def test_rate_limit_reports_how_long_to_wait():
    async def go():
        async with mock_client(lambda r: httpx.Response(429, headers={"retry-after": "17"})) as c:
            await convert_part("t", "k", client=c)

    with pytest.raises(AIRateLimited) as e:
        run(go())
    assert e.value.retry_after == 17


@pytest.mark.parametrize("response", [
    httpx.Response(500, json={"error": "boom"}),
    httpx.Response(200, json={"choices": [{"message": {"content": "not json at all"}}]}),
    httpx.Response(200, json={"choices": [{"message": {"content": "[1, 2]"}}]}),
    httpx.Response(200, json={"unexpected": True}),
])
def test_ai_failures_become_a_clear_error(response):
    async def go():
        async with mock_client(lambda r: response) as c:
            await convert_part("t", "k", client=c)

    with pytest.raises(AIUnavailable):
        run(go())


# ─── Endpoints ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("user", [STUDENT, MENTOR], ids=["student", "mentor"])
def test_students_and_mentors_cannot_use_import(make_client, user):
    c = make_client(user)
    assert c.post("/api/admin/mcq-import/normalize", json={"parts": [[q(correct_option=0)]]}).status_code == 403
    assert c.post("/api/admin/mcq-import/pdf/convert", json={"text": "x"}).status_code == 403
    assert c.post("/api/admin/mcq-import/pdf/extract", files={"paper": ("p.pdf", text_pdf(PAPER), "application/pdf")}).status_code == 403


@pytest.mark.parametrize("user", [ADMIN, EDITOR], ids=["admin", "mcq_editor"])
def test_admins_and_mcq_editors_can_import(make_client, user):
    c = make_client(user)
    res = c.post("/api/admin/mcq-import/normalize", json={"parts": [[q(answer="b")]]})
    assert res.status_code == 200 and res.json()["sections"][0]["questions"][0]["correct_option"] == 1
    ex = c.post("/api/admin/mcq-import/pdf/extract", files={"paper": ("p.pdf", text_pdf(PAPER), "application/pdf")}, data={"mode": "text"})
    assert ex.status_code == 200 and "Ind AS 2" in ex.json()["parts"][0]["text"]


def test_extract_includes_a_separate_answer_key_pdf(make_client):
    res = make_client(ADMIN).post("/api/admin/mcq-import/pdf/extract", files={
        "paper": ("p.pdf", text_pdf(PAPER), "application/pdf"),
        "answer_key": ("k.pdf", text_pdf("ANSWER KEY\n1. (b)"), "application/pdf"),
    })
    labels = [p["label"] for p in res.json()["parts"]]
    assert labels[0].startswith("Question paper") and labels[-1].startswith("Answer key")


def test_extract_rejects_a_non_pdf_with_a_reason(make_client):
    res = make_client(ADMIN).post("/api/admin/mcq-import/pdf/extract", files={"paper": ("p.pdf", b"not a pdf", "application/pdf")})
    assert res.status_code == 400 and "isn't a PDF" in res.json()["detail"]


def test_normalize_explains_an_unreadable_file(make_client):
    res = make_client(ADMIN).post("/api/admin/mcq-import/normalize", json={"parts": [{"hello": "world"}]})
    assert res.status_code == 400 and "format" in res.json()["detail"]


class _Settings:
    def __init__(self, key):
        self.groq_api_key = key


def test_convert_without_a_groq_key_says_how_to_fix_it(make_client, monkeypatch):
    monkeypatch.setattr("app.routers.mcq_import.get_settings", lambda: _Settings(""))
    res = make_client(ADMIN).post("/api/admin/mcq-import/pdf/convert", json={"text": "x"})
    assert res.status_code == 503 and "GROQ_API_KEY" in res.json()["detail"]


def test_convert_passes_on_the_wait_and_returns_the_carry(make_client, monkeypatch):
    monkeypatch.setattr("app.routers.mcq_import.get_settings", lambda: _Settings("k"))

    async def limited(*a, **k):
        raise AIRateLimited(12.5)
    monkeypatch.setattr("app.routers.mcq_import.convert_part", limited)
    res = make_client(ADMIN).post("/api/admin/mcq-import/pdf/convert", json={"text": "x"})
    assert res.status_code == 429 and res.json()["retryAfter"] == 12.5 and res.headers["retry-after"] == "13"

    async def ok(text, key, case_context=None, image=None):
        assert case_context == "Earlier passage"
        return part([case("New passage"), case()])
    monkeypatch.setattr("app.routers.mcq_import.convert_part", ok)
    res = make_client(ADMIN).post("/api/admin/mcq-import/pdf/convert", json={"text": "x", "carry": "Earlier passage"})
    assert res.status_code == 200 and res.json()["carry"]["case"] == "New passage"


def test_convert_reports_ai_failures_as_502(make_client, monkeypatch):
    monkeypatch.setattr("app.routers.mcq_import.get_settings", lambda: _Settings("k"))

    async def broken(*a, **k):
        raise AIUnavailable("The AI returned an unreadable answer for this part.")
    monkeypatch.setattr("app.routers.mcq_import.convert_part", broken)
    res = make_client(ADMIN).post("/api/admin/mcq-import/pdf/convert", json={"text": "x"})
    assert res.status_code == 502 and "unreadable" in res.json()["detail"]


def test_saving_a_question_with_no_answer_is_refused_not_saved_as_a(make_client, fake_db):
    """Imported questions without an answer carry correct_option null. The
    save endpoint used to coerce that to 0 (option A) silently."""
    body = {"title": "Imported", "level": "FINAL", "groupName": "GROUP_1", "subjectCode": "FR", "status": "draft",
            "sections": [{"title": "Section A", "questions": [{"content": "Q?", "options": ["a", "b"], "correct_option": None}]}]}
    res = make_client(ADMIN).post("/api/admin/mcq-sets", json=body)
    assert res.status_code == 400 and "no correct answer" in res.json()["detail"]
    assert fake_db.table("questions").select("*").execute().data == []

    body["sections"][0]["questions"][0]["correct_option"] = 1
    assert make_client(ADMIN).post("/api/admin/mcq-sets", json=body).status_code == 200
    assert fake_db.table("questions").select("*").execute().data[0]["correct_option"] == 1


# ─── "Best accuracy": pages read as images ───────────────────────────────────
# Maths laid out by an equation editor is lost in a PDF's text layer (1/2
# comes out as "1" and "2" on separate lines, P(Ā∩B̄) as P(A∩B)), so by
# default each page is rendered and read by the vision model instead.

def test_pages_render_to_jpeg_images_one_per_page():
    images = render_pages(text_pdf(PAPER, "2. Second page?\n(a) Yes\n(b) No"))
    assert len(images) == 2
    for b64 in images:
        raw = base64.b64decode(b64)
        assert raw[:3] == b"\xff\xd8\xff"  # JPEG
        assert 50_000 > len(raw) > 1_000


def test_image_mode_accepts_a_scanned_page_that_text_mode_rejects():
    w = PdfWriter()
    w.add_blank_page(width=612, height=792)  # no text layer, like a scan
    buf = io.BytesIO()
    w.write(buf)
    assert len(render_pages(buf.getvalue())) == 1
    with pytest.raises(ImportProblem, match="scanned"):
        extract_pages(buf.getvalue())


@pytest.mark.parametrize("data,message", [(b"", "empty"), (b"not a pdf", "isn't a PDF"), (b"%PDF-1.4 junk", "couldn't be read")])
def test_image_mode_rejects_bad_files_with_a_reason(data, message):
    with pytest.raises(ImportProblem, match=message):
        render_pages(data)


def test_image_mode_rejects_password_protected_pdfs():
    w = PdfWriter()
    w.add_blank_page(width=612, height=792)
    w.encrypt(user_password="secret", owner_password="owner")
    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(ImportProblem, match="password"):
        render_pages(buf.getvalue())


def test_extract_defaults_to_page_images(make_client):
    res = make_client(ADMIN).post("/api/admin/mcq-import/pdf/extract", files={
        "paper": ("p.pdf", text_pdf(PAPER, "2. Next?\n(a) x\n(b) y"), "application/pdf"),
        "answer_key": ("k.pdf", text_pdf("ANSWER KEY\n1. (b)"), "application/pdf"),
    })
    assert res.status_code == 200 and res.json()["mode"] == "image"
    parts = res.json()["parts"]
    assert [p["label"] for p in parts] == ["Question paper · page 1", "Question paper · page 2", "Answer key · page 1"]
    assert all("image" in p and "text" not in p for p in parts)


def test_extract_rejects_an_unknown_mode(make_client):
    res = make_client(ADMIN).post("/api/admin/mcq-import/pdf/extract",
                                  files={"paper": ("p.pdf", text_pdf(PAPER), "application/pdf")}, data={"mode": "magic"})
    assert res.status_code == 400


@pytest.mark.parametrize("body", [{}, {"text": "x", "image": "aGk="}, {"carry": "only a carry"}])
def test_convert_needs_exactly_one_of_text_or_image(make_client, monkeypatch, body):
    monkeypatch.setattr("app.routers.mcq_import.get_settings", lambda: _Settings("k"))
    assert make_client(ADMIN).post("/api/admin/mcq-import/pdf/convert", json=body).status_code == 400


def test_convert_passes_a_page_image_through(make_client, monkeypatch):
    monkeypatch.setattr("app.routers.mcq_import.get_settings", lambda: _Settings("k"))
    seen = {}

    async def fake(text, key, case_context=None, image=None):
        seen.update(text=text, image=image)
        return part([q(correct_option=0)])
    monkeypatch.setattr("app.routers.mcq_import.convert_part", fake)
    res = make_client(ADMIN).post("/api/admin/mcq-import/pdf/convert", json={"image": "aGVsbG8="})
    assert res.status_code == 200 and seen == {"text": None, "image": "aGVsbG8="}


def test_vision_request_sends_the_page_to_the_vision_model():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    async def go():
        async with mock_client(handler) as c:
            return await convert_part(None, "k", client=c, image="aGVsbG8=", case_context="Delta passage")

    run(go())
    body = seen["body"]
    assert body["model"] == GROQ_VISION_MODEL and "reasoning_effort" not in body
    assert body["messages"][0]["content"] == IMAGE_SYSTEM_PROMPT
    text_part, image_part = body["messages"][1]["content"]
    assert "Delta passage" in text_part["text"]
    assert image_part == {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,aGVsbG8="}}


def test_convert_part_refuses_both_or_neither_input():
    with pytest.raises(ValueError):
        run(convert_part("some text", "k", image="aGk="))
    with pytest.raises(ValueError):
        run(convert_part(None, "k"))


@pytest.mark.parametrize("prompt", [TEXT_SYSTEM_PROMPT, IMAGE_SYSTEM_PROMPT], ids=["text", "image"])
def test_both_modes_are_told_how_to_write_maths(prompt):
    for rule in ("numerator first", "x²", "log₂", "U+0304", "∩ ∪", "√"):
        assert rule in prompt
