import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ats  # noqa: E402


def make_line(text, x0=50.0, x1=550.0, y0=700.0, y1=712.0, page=0, index=0):
    return ats.Line(
        text=text, x0=x0, x1=x1, y0=y0, y1=y1, page=page, index=index
    )


def stacked_lines(texts, page=0):
    """Return lines stacked top-to-bottom, one visual row each."""
    lines = []
    for i, text in enumerate(texts):
        top = 800.0 - 15.0 * i
        lines.append(make_line(text, y0=top, y1=top + 12.0, page=page, index=i))
    return lines


GOOD_TEXT = """Sample Candidate
Full Stack Engineer
+55 11 0000-0000
candidate@example.com
https://www.linkedin.com/in/sample-candidate

Summary
Experienced engineer with five years building web applications.

Experience
Acme Corp
Engineer
Remote | 01/2023 - Present
Built the platform with Python and Docker.
Managed a team of five engineers.

Education
State University
BSc Computer Science
01/2012 - 01/2016

Skills
Python, Docker, TypeScript

Languages
English
"""

GOOD_CV = {
    "personal": {
        "name": "Sample Candidate",
        "title": "Full Stack Engineer",
        "phone": "+55 11 0000-0000",
        "email": "candidate@example.com",
        "linkedin": "https://www.linkedin.com/in/sample-candidate",
        "location": "Remote",
    },
    "summary": "Experienced engineer with five years building web applications.",
    "experience": [
        {
            "org": "Acme Corp",
            "location": "Remote",
            "role": "Engineer",
            "start": "01/2023",
            "end": "Present",
            "bullets": [
                "Built the platform with Python and Docker.",
                "Managed a team of five engineers.",
            ],
        }
    ],
    "education": [
        {
            "institution": "State University",
            "location": "Metropolis",
            "degree": "BSc Computer Science",
            "start": "01/2012",
            "end": "01/2016",
            "bullets": [],
        }
    ],
    "courses": [],
    "skills": [{"group": "Core", "tags": ["Python", "Docker", "TypeScript"]}],
    "languages": [{"name": "English", "level": "Fluent", "dots": 5}],
}

GOOD_LINES = stacked_lines(
    [
        "Sample Candidate",
        "Full Stack Engineer",
        "+55 11 0000-0000 | candidate@example.com | https://www.linkedin.com/in/sample-candidate",
        "Summary",
        "Experienced engineer with five years building web applications.",
        "Experience",
        "Acme Corp",
        "Engineer",
        "Remote | 01/2023 - Present",
        "Built the platform with Python and Docker.",
        "Managed a team of five engineers.",
        "Education",
        "State University",
        "BSc Computer Science",
        "01/2012 - 01/2016",
        "Skills",
        "Python, Docker, TypeScript",
        "Languages",
        "English",
    ]
)


@pytest.fixture
def good_pdf(tmp_path):
    pdf = tmp_path / "cv.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake body")
    return pdf


@pytest.fixture
def mock_extraction(monkeypatch):
    """Make run_checks read from the synthetic fixtures instead of a real PDF."""
    monkeypatch.setattr(ats, "extract_pdf_text", lambda path: GOOD_TEXT)
    monkeypatch.setattr(ats, "extract_lines", lambda path: GOOD_LINES)
    return GOOD_TEXT, GOOD_LINES