"""Gate: the leadership scorer must understand Portuguese, not just English.

Every PT CV was scoring 0 on leadership despite carrying real signals
("mentorei", "liderei", "estratégia"), because LEADERSHIP_WORDS is English-only
and matching uses word boundaries: \bmentor\b never matches "mentorei".

The alternative fix, writing English words into a Portuguese document to satisfy
a metric, would corrupt the CV. The scorer is the thing that was wrong.
"""

import json
import re
from pathlib import Path

import pytest

import ats

ROOT = Path(__file__).resolve().parent.parent

PT_LANGUAGES = [{"name": "Português", "level": "Nativo", "dots": 5}]
EN_LANGUAGES = [{"name": "English", "level": "Native", "dots": 5}]


def _pt_cvs():
    return sorted(ROOT.glob("companies/*/cv-pt.json"))


def test_scorer_knows_portuguese_leadership():
    assert ats.LEADERSHIP_WORDS_PT, "no Portuguese leadership vocabulary declared"


def test_portuguese_bullets_score():
    cv = {
        "languages": PT_LANGUAGES,
        "experience": [{"bullets": [
            "Mentorei novos engenheiros e liderei a evolução do Design System.",
            "Conduzi o refinamento do backlog técnico como dono das entregas.",
        ]}],
    }
    check = ats.score_leadership(cv)
    assert check.score > 0, f"PT leadership scored 0: {check.detail}"


def test_english_bullets_still_score():
    cv = {"languages": EN_LANGUAGES,
          "experience": [{"bullets": ["Managed the team and mentored engineers."]}]}
    check = ats.score_leadership(cv)
    assert check.score > 0, f"EN leadership scored 0: {check.detail}"


def test_english_cv_does_not_borrow_pt_words():
    """An EN CV must not be credited for Portuguese-only signals."""
    cv = {"languages": EN_LANGUAGES,
          "experience": [{"bullets": ["Mentorei a equipe e liderei a entrega."]}]}
    assert ats.score_leadership(cv).score == 0


@pytest.mark.skipif(not _pt_cvs(), reason="no PT CVs present")
def test_pt_leadership_evidence_is_not_scored_zero():
    """A PT CV that carries PT leadership evidence must register it.

    A CV with no leadership evidence at all is allowed to score 0, so the
    assertion is conditional on the evidence being present.
    """
    silent = []
    for path in _pt_cvs():
        cv = json.loads(path.read_text())
        body = " ".join(ats._all_bullets(cv)).lower()
        evidence = any(
            re.search(rf"\b{re.escape(w)}\b", body) for w in ats.LEADERSHIP_WORDS_PT
        )
        if evidence and ats.score_leadership(cv).score == 0:
            silent.append(path.parts[-2])
    assert not silent, f"PT leadership evidence ignored in: {', '.join(silent)}"