# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.

"""The result page is themable, and Intent's version scores each domain separately.

One aggregate percentage hides the thing a practice exam exists to reveal. A 63%
carried by six solid domains and one that scored zero is a different problem from a
63% that is uniformly thin, and only the first has an obvious next action.
"""

import re
from pathlib import Path

import pytest

from now_lms import lms_app
from now_lms.themes import get_evaluation_result_template

PLATFORM_TEMPLATE = "evaluations/evaluation_result.html"


@pytest.fixture
def app_context():
    with lms_app.app_context():
        yield


def _override_path(theme: str) -> Path:
    from now_lms.config import DIRECTORIO_PLANTILLAS

    return Path(DIRECTORIO_PLANTILLAS) / "themes" / theme / "overrides" / "evaluation_result.j2"


def test_falls_back_to_the_platform_template_when_the_theme_has_no_override(app_context, monkeypatch):
    monkeypatch.setattr("now_lms.themes.get_current_theme", lambda: "now_lms")
    assert not _override_path("now_lms").exists()
    assert get_evaluation_result_template() == PLATFORM_TEMPLATE


def test_the_intent_theme_serves_its_own_result_surface(app_context, monkeypatch):
    monkeypatch.setattr("now_lms.themes.get_current_theme", lambda: "intent_learn")
    assert _override_path("intent_learn").exists()
    assert get_evaluation_result_template() == "themes/intent_learn/overrides/evaluation_result.j2"


def test_proficiency_walks_every_question_not_only_the_answered_ones():
    """The defect this template was written to avoid.

    Iterating `attempt.answers` is the obvious way to build the per-domain tally and it
    is wrong: an unanswered question has no Answer row, so it would vanish from its
    domain's denominator. A member who skipped six of thirteen items in one domain
    would be shown a percentage of the seven they attempted — inflating exactly the
    domain they most need to see is weak.

    Asserted against the source because the alternative is standing up a full attempt
    with a deliberate hole in it, and the loop header is the whole guarantee.

    Updated 2026-09-02: "every question" now means every question ON THE PAPER, which
    is not the same as every question in the evaluation. Once an evaluation became a
    pool that each attempt draws from, walking `attempt.evaluation.questions` tallied
    the entire bank — a 60-item sitting over a 583-item pool reported on all 583 and
    published the answers to the 523 the member never saw. The paper still contains
    unanswered questions, so the original guarantee is untouched.
    """
    source = _override_path("intent_learn").read_text(encoding="utf-8")

    tally = source.split("<!doctype html>")[0]
    assert "for question in paper" in tally, "the tally must walk every question on the paper"

    body = source.split("<!doctype html>")[1]
    assert "for question in attempt.evaluation.questions" not in body, (
        "the result page must never iterate the evaluation's whole question set — "
        "that renders and reveals questions this attempt never showed"
    )

    loops = re.findall(r"{%-?\s*for\s+(\w+)\s+in\s+([^%]+?)\s*-?%}", tally)
    assert loops, "expected the tally block to contain a loop"
    for _var, iterable in loops:
        assert "attempt.answers" not in iterable, (
            f"the per-domain tally must not iterate answers ({iterable.strip()}) — "
            "unanswered questions would drop out of their domain's denominator"
        )
