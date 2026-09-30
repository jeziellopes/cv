"""Gate: a short project name must not match inside an unrelated word.

Adding "memo" to the deny list flagged every CV containing "memória" or
"memorável" under a substring check. Names are matched on word boundaries.
"""

from approvals import leaked

CONFIG = {
    "approved": ["Solitti"],
    "approved_by_company": {"acme": ["memo"]},
    "internal": ["memo", "XRay", "RespiraPsi"],
}


def test_short_name_does_not_match_inside_a_word():
    """Portuguese prose contains "memo" inside memória and memorável."""
    text = "Trabalhei com memória de produto e algo memorável para o usuário."
    assert leaked(text, "other", CONFIG) == []


def test_short_name_matches_as_a_whole_word():
    assert leaked("Construí o memo em Python.", "other", CONFIG) == ["memo"]


def test_approved_name_is_not_flagged():
    assert leaked("Construí o memo em Python.", "acme", CONFIG) == []


def test_longer_names_still_match():
    assert leaked("Usei o XRay em produção.", "other", CONFIG) == ["XRay"]


def test_case_and_accents_are_handled():
    assert leaked("O MEMO roda local.", "other", CONFIG) == ["memo"]