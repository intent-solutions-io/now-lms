# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.

"""The exam form: drawing a paper, shuffling it, and reading it back.

An evaluation with a ``draw_size`` is a POOL, not a paper. Each attempt draws its
own questions, weighted across the certification's domains, and shuffles each
question's options. Two sittings of the same exam are therefore two different
papers, which is the only reason a deep bank is worth authoring: without a draw,
a 728-item bank still serves the same subset in the same order every time.

The drawn paper is written to ``EvaluationAttempt.form_json`` at the moment the
sitting starts. Everything downstream — rendering, grading, review — reads that
record rather than re-deriving anything, so a refresh, a crash, or a move to
another device resumes the same paper, and the grade is computed against the
options in the order the candidate actually saw them.

Nothing here reaches for the clock or the request. It is pure enough to test.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterable

FORM_VERSION = 1


def _by_domain(questions: Iterable) -> dict:
    """Group questions by ``domain_key``, preserving their stored order.

    Questions with no domain (hand-authored in the instructor UI, or seeded before
    the domain columns existed) collect under ``None`` and are drawn from last,
    which keeps them usable without letting them distort a weighted draw.
    """
    grouped: dict = {}
    for question in questions:
        grouped.setdefault(getattr(question, "domain_key", None), []).append(question)
    return grouped


def domain_targets(weights: dict, total: int) -> dict:
    """Split ``total`` across domains by weight, using largest-remainder.

    Rounding each domain independently loses or gains items, and an exam that is
    59 or 61 questions when it claims 60 is a defect a candidate can see. Largest
    remainder distributes the rounding loss deterministically so the parts sum to
    the whole.
    """
    if not weights or total <= 0:
        return {}
    weight_sum = sum(weights.values()) or 1
    exact = {key: total * weight / weight_sum for key, weight in weights.items()}
    targets = {key: int(value) for key, value in exact.items()}
    short = total - sum(targets.values())
    # Hand the remaining places to the domains with the largest fractional part,
    # tie-broken by key so the split is stable rather than dict-order dependent.
    order = sorted(exact, key=lambda key: (-(exact[key] - int(exact[key])), key))
    for index in range(short):
        targets[order[index % len(order)]] += 1
    return targets


def draw_questions(questions: list, draw_size: int, weights: dict | None = None, rng=None) -> list:
    """Draw ``draw_size`` questions, weighted by domain where weights are given.

    Falls back to a flat random sample when the pool carries no usable domains or
    no weights were supplied. A domain that cannot fill its target contributes
    everything it has, and the shortfall is made up from the rest of the pool, so
    a thin domain shortens nothing: the paper is always ``draw_size`` long while
    the pool can fill it at all.
    """
    rng = rng or random.Random()
    pool = list(questions)
    if draw_size >= len(pool):
        drawn = pool[:]
        rng.shuffle(drawn)
        return drawn

    grouped = _by_domain(pool)
    usable = {key: rows for key, rows in grouped.items() if key is not None}
    if not usable or not weights:
        return rng.sample(pool, draw_size)

    # Only weight the domains this pool can actually serve; a blueprint naming a
    # domain the pool has none of would otherwise silently shrink the paper.
    live_weights = {key: weight for key, weight in weights.items() if usable.get(key)}
    if not live_weights:
        return rng.sample(pool, draw_size)

    targets = domain_targets(live_weights, draw_size)
    drawn: list = []
    taken: set = set()
    for key, target in targets.items():
        available = usable.get(key, [])
        picked = rng.sample(available, min(target, len(available)))
        drawn.extend(picked)
        taken.update(id(question) for question in picked)

    if len(drawn) < draw_size:
        remainder = [question for question in pool if id(question) not in taken]
        rng.shuffle(remainder)
        drawn.extend(remainder[: draw_size - len(drawn)])

    rng.shuffle(drawn)
    return drawn[:draw_size]


def build_form(questions: list, evaluation, weights: dict | None = None, rng=None) -> dict:
    """Build the paper for one attempt: which questions, and in what option order.

    Option order is stored per question rather than re-randomised at render time.
    Re-randomising would reshuffle the options under a candidate on every page
    load, and would grade against an order they never saw.
    """
    rng = rng or random.Random()
    draw_size = getattr(evaluation, "draw_size", None)
    drawn = draw_questions(questions, draw_size, weights, rng) if draw_size else list(questions)

    items = []
    for question in drawn:
        options = list(question.options)
        rng.shuffle(options)
        items.append({
            "question_id": question.id,
            "option_ids": [option.id for option in options],
            # The paper is FROZEN here, text and keys included. Reading these back
            # off the live rows meant an instructor editing a question mid-sitting
            # changed the paper under the candidate: a deleted question shortened
            # it while the score kept the original denominator, an added option
            # appeared unannounced, and an edited key regraded work already done.
            # What was shown is what is graded.
            "text": question.text,
            "domain_key": getattr(question, "domain_key", None),
            "domain_name": getattr(question, "domain_name", None),
            "explanation": getattr(question, "explanation", None),
            "options": [
                {"id": option.id, "text": option.text, "is_correct": bool(option.is_correct)}
                for option in options
            ],
        })
    return {"version": FORM_VERSION, "items": items}


def dump_form(form: dict) -> str:
    """Serialise a form for ``EvaluationAttempt.form_json``."""
    return json.dumps(form, separators=(",", ":"))


def load_form(raw: str | None) -> dict | None:
    """Read a stored form back, tolerating anything that is not one.

    A form that will not parse, or that comes from a future version, is treated as
    absent rather than raising: a candidate mid-sitting gets the evaluation's
    stored questions instead of a 500, and their answers still grade.
    """
    if not raw:
        return None
    try:
        form = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(form, dict) or form.get("version") != FORM_VERSION:
        return None
    if not isinstance(form.get("items"), list):
        return None
    return form


def form_questions(form: dict | None, evaluation) -> list:
    """The questions of this paper, exactly as it was shown.

    Served from the frozen copy in the form, not from the live rows, so a paper
    cannot change under a candidate who is sitting it, and a finished attempt
    reviews the exam they actually took. A form written before the text was frozen
    falls back to the live rows, which is the behaviour those attempts already had.
    """
    if not form:
        return [_ordered(question, None) for question in evaluation.questions]

    by_id = {question.id: question for question in evaluation.questions}
    ordered = []
    for item in form["items"]:
        if item.get("options"):
            ordered.append(_FrozenQuestion(item))
            continue
        # Pre-freeze form: fall back to the live row, skipping one since deleted.
        question = by_id.get(item.get("question_id"))
        if question is not None:
            ordered.append(_ordered(question, item.get("option_ids")))
    return ordered


class _FrozenOption:
    """An option exactly as the candidate saw it."""

    __slots__ = ("id", "is_correct", "text")

    def __init__(self, raw):
        self.id = raw.get("id")
        self.text = raw.get("text") or ""
        self.is_correct = bool(raw.get("is_correct"))


class _FrozenQuestion:
    """A question exactly as the candidate saw it, options in the order shown."""

    __slots__ = ("domain_key", "domain_name", "explanation", "format", "id", "options", "text", "type")

    def __init__(self, item):
        self.id = item.get("question_id")
        self.text = item.get("text") or ""
        self.domain_key = item.get("domain_key")
        self.domain_name = item.get("domain_name")
        self.explanation = item.get("explanation")
        self.options = [_FrozenOption(o) for o in item.get("options", [])]
        # Every seeded question is stored as "multiple"; grading compares the full
        # selected set against the full correct set either way.
        self.type = "multiple"
        self.format = "multi" if sum(1 for o in self.options if o.is_correct) > 1 else "single"


class _FormQuestion:
    """One question as this paper shows it: the row, with options in form order."""

    __slots__ = ("options", "question")

    def __init__(self, question, options):
        self.question = question
        self.options = options

    def __getattr__(self, name):
        # Everything the templates already read off a Question keeps working.
        return getattr(self.question, name)


def _ordered(question, option_ids):
    options = list(question.options)
    if option_ids:
        position = {option_id: index for index, option_id in enumerate(option_ids)}
        # An option the form does not name sorts last rather than vanishing, so an
        # option added to a question mid-sitting is still answerable.
        options.sort(key=lambda option: position.get(option.id, len(position)))
    return _FormQuestion(question, options)


# ---------------------------------------------------------------------------
# Scoring a sitting
# ---------------------------------------------------------------------------

SCALE_MIN = 100
SCALE_MAX = 1000


def scale_score(raw: int, total: int) -> int:
    """Map a raw score onto the 100-1000 band the certifications report on.

    A plain linear map, deliberately. The real conversion is proprietary and
    unpublished, so anything curve-shaped here would be invented precision. The
    surface that shows this number says so.
    """
    if total <= 0:
        return SCALE_MIN
    return round(SCALE_MIN + (raw / total) * (SCALE_MAX - SCALE_MIN))


def raw_needed(cut: int, total: int) -> int:
    """The smallest raw score whose SCALED score reaches ``cut``.

    Derived against ``scale_score`` rather than independently, because that
    function rounds. Ceiling the unrounded value disagrees with it near the
    boundary: on a 106-question paper it gives 74 while 73 already displays as
    720, so a candidate would be told they need one more than the score report
    actually requires.
    """
    if total <= 0:
        return 0
    span = SCALE_MAX - SCALE_MIN
    candidate = min(total, max(0, -(-((cut - SCALE_MIN) * total) // span)))
    # Walk down over any question the rounding already covers.
    while candidate > 0 and scale_score(candidate - 1, total) >= cut:
        candidate -= 1
    return candidate


def domain_breakdown(graded: list) -> list:
    """Per-domain correct/total, in descending size, for the score report.

    ``graded`` is a list of ``(question, was_correct)``. Questions with no domain
    are left out rather than bucketed as "unknown": a diagnostic that names a
    domain a candidate cannot go and study is noise.
    """
    buckets: dict = {}
    for question, correct in graded:
        key = getattr(question, "domain_key", None)
        if not key:
            continue
        bucket = buckets.setdefault(key, {"key": key, "name": getattr(question, "domain_name", None) or key,
                                          "correct": 0, "total": 0})
        bucket["total"] += 1
        if correct:
            bucket["correct"] += 1
    rows = list(buckets.values())
    for row in rows:
        row["share"] = row["correct"] / row["total"] if row["total"] else 0.0
    rows.sort(key=lambda row: (-row["total"], row["name"]))
    return rows
