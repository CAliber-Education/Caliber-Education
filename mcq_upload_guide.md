# Comprehensive MCQ Configuration Guide

This document explains how to build a CA Hierarchy MCQ Test Paper. You can type it in the **Manual Editor**, or fill in a whole paper at once with **Import from PDF** or **Upload JSON** (both on the **Sections & Questions** tab).

All three work for both **normal MCQs** and **case-based MCQs**.

---

## Method 1: The Manual Editor (Step-by-Step)

The manual editor has been entirely redesigned so that Case Scenarios and Normal Questions sit directly side-by-side inside your Exam Sections.

1. **Access the Hierarchy Engine:** Open your Admin Dashboard and click the **MCQ Hierarchy** tab.
2. **Create/Edit a Paper:** Click "+ New Paper" or edit an existing one. Define the Level, Group, Subject, duration, and marking logic.
3. **Go to Sections & Questions:** Click the final tab. If the paper is empty, click **+ Manual Section** to create a block (e.g., "Section A: Compulsory").
4. **Add Items to the Section:**
   * **To add a standard MCQ:** Click **+ Add Normal Question**. You'll get a clean form to write the question, 4 options, marks, and the correct option.
   * **To add a Case Study:** Click **+ Add Case Study Block**. 
     - A massive text block will appear for your reading passage/narrative.
     - Beneath that, a special **"+ Add Sub-Question"** button appears. Click it to strictly bind consecutive MCQs to that specific reading passage.
5. **Save the Exam:** Set **Status** on the "Hierarchy & Settings" tab (Draft keeps it hidden from students; Published makes it live) and click **Save Paper**.

---

## Method 2: Import from PDF (fastest)

1. Open **Sections & Questions** and click **Import from PDF**.
2. Choose the **question paper PDF**. If the answers are in a separate file, also choose the **answer key PDF**.
3. Choose how it reads the paper:
   - **Best accuracy (recommended)** — reads each page as an image, the way you see it. Fractions (1/2), powers (x²), log bases (log₂), bars (Ā, B̄) and symbols (∩ ∪ √) come out right, and scanned papers work too. About **1 page a minute** on the free AI plan.
   - **Faster** — reads the PDF's text. Fine for theory papers (Law, Audit), but maths and symbols can come out wrong — fractions upside down or split, bars and powers lost — and scanned papers won't work.
4. Click **Import** and leave it open — on the free plan you'll see a countdown between pages. It carries on by itself.
5. Review, then **Save Paper**.

Maths is stored as plain text with symbols (e.g. `P(Ā∩B̄)`, `log₄(x² + x)`, `(2a + b)/(a + 2b)`), so it shows the same in the editor and for students.

What it reads: sections, questions, options, answers (printed under each question, or from an answer key anywhere in the paper or a separate PDF), explanations, marks, and case studies. For a new, empty paper it also fills in the **title, duration, total marks and subject** on Hierarchy & Settings.

What to check:
- Questions **highlighted in yellow** need a look — e.g. "No answer found in the file", or fewer than 4 options found. **Save stays blocked until every question has an answer.**
- Answers are **never guessed**: if the paper doesn't print one, the question is left unanswered and highlighted for you — even if the AI tried to supply one ("The AI suggested an answer that isn't printed in the paper").

---

## Method 3: Upload JSON

1. Open **Sections & Questions** and click **Upload JSON**.
2. Choose your `.json` file, then review and **Save Paper** as above.

If the paper already has questions, you're asked before the new ones are added after them. Missing or unclear answers are highlighted, never set to option A.

Accepted layouts: the format below (a list of sections), the same wrapped as `{"sections": [...]}`, or a plain list of questions. Answers can be `"correct_option": 0` (0 = a, 1 = b, …) or a letter such as `"answer": "b"`. Option labels like `(a)` and question numbers like `Q1.` are removed automatically.

### JSON format

The recommended layout is an **array of sections**. Each section contains a `title` and an array of `questions`.
Case Study questions have `type: "case"` and define the `case_narrative` directly on the first sub-question (the system automatically groups them!).

```json
[
  {
    "title": "Section A: Independent Assessment",
    "questions": [
      {
        "type": "normal",
        "content": "According to Ind AS 2, what is the measurement principle for inventory?",
        "options": [
          "Lower of cost or net realizable value",
          "Fair value less costs to sell",
          "Historical cost",
          "Replacement cost"
        ],
        "correct_option": 0,
        "explanation": "Ind AS 2 standard core principle.",
        "marks": 2,
        "negative_marks": 0.5,
        "difficulty": "medium"
      }
    ]
  },
  {
    "title": "Section B: Integrated Case Studies",
    "questions": [
      {
        "type": "case",
        "case_narrative": "ABC Ltd is a manufacturing company. During the year, they purchased machinery for Rs 10 Lakhs. They also incurred installation costs of Rs 50,000. Due to a union strike, there was an idle time loss of Rs 20,000...",
        "content": "What is the total capitalizable cost of the machinery?",
        "options": ["Rs 10,00,000", "Rs 10,50,000", "Rs 10,70,000", "Rs 10,30,000"],
        "correct_option": 1,
        "explanation": "Purchase cost + installation. Idle time is ignored.",
        "marks": 2,
        "negative_marks": 0
      },
      {
        "type": "case",
        "content": "How should the Rs 20,000 idle time loss be treated in the financials?",
        "options": ["Capitalized", "Deferred", "Charged to P&L", "Ignored"],
        "correct_option": 2,
        "explanation": "Abnormal losses are P&L charged.",
        "marks": 2,
        "negative_marks": 0
      }
    ]
  }
]
```

### Auto-Grouping Logic:
If the system sees consecutive questions with `type: "case"`, it automatically assumes they belong to the SAME case study block. You only need to provide the `case_narrative` on the **first question** of the cluster!

A new `case_narrative` starts a new case study: when two case studies come one after another, the importer puts the second in its own section (e.g. "Part B — Case 2") so they never merge into one.
