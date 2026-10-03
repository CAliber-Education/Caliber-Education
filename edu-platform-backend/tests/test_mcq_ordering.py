"""Deterministic ordering: quiz retrieval must return sections/questions by
their explicit order_index, not by whatever order the fake store happens to
hold them in (which stands in for Postgres/PostgREST's unspecified default
row order — the exact thing this fix removes a dependency on).
"""


def _seed_unordered_paper(fake_db, paper_id="paper-1", section_id="sec-1", locked=False):
    fake_db.seed("mcq_papers", [{
        "id": paper_id, "title": "Ordering Test", "level": "FINAL", "status": "published",
        "subject_code": "FR", "is_locked": locked, "shuffle_questions": False,
    }])
    fake_db.seed("exam_sections", [{"id": section_id, "paper_id": paper_id, "title": "Section A", "order_index": 0}])
    # Deliberately inserted out of order_index order.
    fake_db.seed("questions", [
        {
            "id": "q-third", "section_id": section_id, "type": "normal",
            "case_narrative": "", "case_group_id": None, "chapter_tag": "General",
            "difficulty": "medium", "marks": 1.0, "negative_marks": 0.0,
            "content": "Third question", "options": ["a", "b"], "correct_option": 0,
            "explanation": "", "order_index": 2,
        },
        {
            "id": "q-first", "section_id": section_id, "type": "normal",
            "case_narrative": "", "case_group_id": None, "chapter_tag": "General",
            "difficulty": "medium", "marks": 1.0, "negative_marks": 0.0,
            "content": "First question", "options": ["a", "b"], "correct_option": 0,
            "explanation": "", "order_index": 0,
        },
        {
            "id": "q-second", "section_id": section_id, "type": "normal",
            "case_narrative": "", "case_group_id": None, "chapter_tag": "General",
            "difficulty": "medium", "marks": 1.0, "negative_marks": 0.0,
            "content": "Second question", "options": ["a", "b"], "correct_option": 0,
            "explanation": "", "order_index": 1,
        },
    ])


def test_get_quiz_orders_questions_by_order_index(make_client, fake_db, student_user):
    _seed_unordered_paper(fake_db)
    client = make_client(student_user)

    res = client.get("/api/quizzes/paper-1")
    assert res.status_code == 200
    questions = res.json()["sections"][0]["questions"]
    assert [q["text"] for q in questions] == ["First question", "Second question", "Third question"]


def test_get_quiz_orders_sections_by_order_index(make_client, fake_db, student_user):
    fake_db.seed("mcq_papers", [{
        "id": "paper-2", "title": "Section Ordering Test", "level": "FINAL", "status": "published",
        "subject_code": "FR", "is_locked": False, "shuffle_questions": False,
    }])
    fake_db.seed("exam_sections", [
        {"id": "sec-b", "paper_id": "paper-2", "title": "Section B", "order_index": 1},
        {"id": "sec-a", "paper_id": "paper-2", "title": "Section A", "order_index": 0},
    ])
    fake_db.seed("questions", [
        {
            "id": "qb", "section_id": "sec-b", "type": "normal", "case_narrative": "",
            "case_group_id": None, "chapter_tag": "General", "difficulty": "medium",
            "marks": 1.0, "negative_marks": 0.0, "content": "In section B",
            "options": ["a", "b"], "correct_option": 0, "explanation": "", "order_index": 0,
        },
        {
            "id": "qa", "section_id": "sec-a", "type": "normal", "case_narrative": "",
            "case_group_id": None, "chapter_tag": "General", "difficulty": "medium",
            "marks": 1.0, "negative_marks": 0.0, "content": "In section A",
            "options": ["a", "b"], "correct_option": 0, "explanation": "", "order_index": 0,
        },
    ])

    client = make_client(student_user)
    res = client.get("/api/quizzes/paper-2")
    assert res.status_code == 200
    sections = res.json()["sections"]
    assert [s["title"] for s in sections] == ["Section A", "Section B"]
