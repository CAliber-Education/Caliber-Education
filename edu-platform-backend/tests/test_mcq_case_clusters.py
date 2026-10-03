"""Case-cluster persistence: admin authoring -> save -> reload, for both the
admin editor's own reload and the student-facing quiz retrieval endpoint.

Regression coverage for the confirmed bug: only the first question of a case
block ever received case_narrative — every sub-question saved with an empty
narrative, so the student-facing panel went blank after question 1 of a case.
"""


def _paper_payload(questions):
    return {
        "title": "Case Cluster Test Paper",
        "subjectCode": "FR",
        "level": "FINAL",
        "groupName": "GROUP_1",
        "status": "published",
        "sections": [{"title": "Section A", "questions": questions}],
    }


CASE_RUN_QUESTIONS = [
    {
        "type": "case",
        "case_narrative": "A retailer is evaluating two financing options for a new warehouse.",
        "content": "What is the effective interest rate of Option A?",
        "options": ["8%", "9%", "10%", "11%"],
        "correct_option": 2,
    },
    {
        # Sub-question — mirrors what the admin UI actually sends: no
        # case_narrative key at all on questions after the head of the run.
        "type": "case",
        "content": "Which option has the lower total cost?",
        "options": ["Option A", "Option B", "Both equal", "Cannot determine"],
        "correct_option": 0,
    },
    {
        "type": "normal",
        "content": "A standalone question unrelated to the case.",
        "options": ["a", "b", "c", "d"],
        "correct_option": 1,
    },
]


def test_admin_save_denormalizes_case_group_id_and_narrative(make_client, admin_user, student_user):
    admin_client = make_client(admin_user, as_admin=True)

    save_res = admin_client.post("/api/admin/mcq-sets", json=_paper_payload(CASE_RUN_QUESTIONS))
    assert save_res.status_code == 200
    paper_id = save_res.json()["id"]

    # Admin reload — the editor must show the same cluster on reopening.
    admin_reload = admin_client.get(f"/api/admin/mcq-sets/{paper_id}")
    assert admin_reload.status_code == 200
    admin_questions = admin_reload.json()["sections"][0]["questions"]
    assert [q["type"] for q in admin_questions] == ["case", "case", "normal"]

    case_q1, case_q2, normal_q = admin_questions
    assert case_q1["case_group_id"] is not None
    assert case_q1["case_group_id"] == case_q2["case_group_id"]
    assert normal_q["case_group_id"] is None

    expected_narrative = "A retailer is evaluating two financing options for a new warehouse."
    assert case_q1["case_narrative"] == expected_narrative
    # The actual bug: sub-question 2's narrative used to save as "".
    assert case_q2["case_narrative"] == expected_narrative

    # Student-facing retrieval must carry the same cluster identity through.
    student_client = make_client(student_user)
    quiz_res = student_client.get(f"/api/quizzes/{paper_id}")
    assert quiz_res.status_code == 200
    quiz_questions = quiz_res.json()["sections"][0]["questions"]
    q1, q2, q3 = quiz_questions
    assert q1["case_group_id"] == q2["case_group_id"] is not None
    assert q1["case_narrative"] == expected_narrative
    assert q2["case_narrative"] == expected_narrative
    assert q3["case_group_id"] is None


def test_admin_save_gives_separate_case_blocks_distinct_group_ids(make_client, admin_user):
    admin_client = make_client(admin_user, as_admin=True)

    questions = [
        {"type": "case", "case_narrative": "Case block one.", "content": "Q1", "options": ["a", "b"], "correct_option": 0},
        {"type": "case", "content": "Q2", "options": ["a", "b"], "correct_option": 0},
        {"type": "normal", "content": "Q3", "options": ["a", "b"], "correct_option": 0},
        {"type": "case", "case_narrative": "Case block two.", "content": "Q4", "options": ["a", "b"], "correct_option": 0},
        {"type": "case", "content": "Q5", "options": ["a", "b"], "correct_option": 0},
    ]
    save_res = admin_client.post("/api/admin/mcq-sets", json=_paper_payload(questions))
    assert save_res.status_code == 200
    paper_id = save_res.json()["id"]

    reload_res = admin_client.get(f"/api/admin/mcq-sets/{paper_id}")
    qs = reload_res.json()["sections"][0]["questions"]
    q1, q2, q3, q4, q5 = qs

    assert q1["case_group_id"] == q2["case_group_id"]
    assert q4["case_group_id"] == q5["case_group_id"]
    # The two case blocks are separated by a normal question and must never
    # be merged into one cluster even though the narrative-matching fallback
    # exists — the group IDs must differ.
    assert q1["case_group_id"] != q4["case_group_id"]
    assert q1["case_narrative"] == "Case block one."
    assert q4["case_narrative"] == "Case block two."
