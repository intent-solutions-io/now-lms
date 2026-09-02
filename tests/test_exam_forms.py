# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 - 2026 BMO Soluciones, S.A.

"""Tests for the exam form: the draw, the shuffle, and the scale.

These cover the properties an exam has to hold whatever the bank looks like: a
paper is exactly as long as it claims, it is weighted to the published blueprint
rather than to whatever the authors wrote most of, a thin domain does not
silently shorten it, and a stored paper reads back in the order it was given.
"""

import random

import pytest

from now_lms.vistas import exam_forms


class FakeOption:
    def __init__(self, option_id, text=None, is_correct=False):
        self.id = option_id
        self.text = text or f"option {option_id}"
        self.is_correct = is_correct


class FakeQuestion:
    def __init__(self, question_id, domain_key, options=4):
        self.id = question_id
        self.domain_key = domain_key
        self.domain_name = domain_key.replace("-", " ").title() if domain_key else None
        self.text = f"stem for {question_id}"
        self.explanation = f"why {question_id}"
        self.options = [
            FakeOption(f"{question_id}-o{i}", f"{question_id} option {i}", is_correct=(i == 0))
            for i in range(options)
        ]


class FakeEvaluation:
    def __init__(self, questions, draw_size=None):
        self.questions = questions
        self.draw_size = draw_size


def bank(counts):
    """A pool with ``counts`` questions per domain."""
    questions = []
    for domain, n in counts.items():
        questions.extend(FakeQuestion(f"{domain}-{i}", domain) for i in range(n))
    return questions


CCA_F = {"agentic": 27, "claudecode": 20, "prompt": 20, "tools": 18, "context": 15}


# --- the split -------------------------------------------------------------


def test_domain_targets_sum_to_the_whole():
    """A 60-item exam is 60 items. Rounding each domain alone loses or gains one."""
    for total in range(1, 121):
        targets = exam_forms.domain_targets(CCA_F, total)
        assert sum(targets.values()) == total


def test_domain_targets_match_the_published_draw():
    assert exam_forms.domain_targets(CCA_F, 60) == {
        "agentic": 16, "claudecode": 12, "prompt": 12, "tools": 11, "context": 9
    }


def test_domain_targets_are_stable_across_calls():
    """Largest remainder must not depend on dict ordering, or two seeds differ."""
    first = exam_forms.domain_targets(CCA_F, 53)
    shuffled = dict(reversed(list(CCA_F.items())))
    assert exam_forms.domain_targets(shuffled, 53) == first


def test_domain_targets_handles_empty_and_zero():
    assert exam_forms.domain_targets({}, 60) == {}
    assert exam_forms.domain_targets(CCA_F, 0) == {}


# --- the draw --------------------------------------------------------------


def test_draw_is_exactly_the_requested_length():
    pool = bank({key: 40 for key in CCA_F})
    drawn = exam_forms.draw_questions(pool, 60, CCA_F, random.Random(1))
    assert len(drawn) == 60


def test_draw_follows_the_blueprint_not_the_bank():
    """The pool is lopsided; the paper must not be.

    This is the whole reason the blueprint is stored rather than derived: a draw
    taken from the pool's own proportions would examine whatever happened to be
    written most.
    """
    pool = bank({"agentic": 200, "claudecode": 40, "prompt": 40, "tools": 40, "context": 40})
    drawn = exam_forms.draw_questions(pool, 60, CCA_F, random.Random(7))
    counts = {}
    for question in drawn:
        counts[question.domain_key] = counts.get(question.domain_key, 0) + 1
    assert counts == exam_forms.domain_targets(CCA_F, 60)


def test_a_thin_domain_does_not_shorten_the_paper():
    """A domain short of its target contributes all it has; the rest fills up."""
    pool = bank({"agentic": 16, "claudecode": 2, "prompt": 30, "tools": 30, "context": 30})
    drawn = exam_forms.draw_questions(pool, 60, CCA_F, random.Random(3))
    assert len(drawn) == 60
    assert len({q.id for q in drawn}) == 60, "a filled-up paper must not repeat a question"


def test_draw_never_repeats_a_question():
    pool = bank({key: 40 for key in CCA_F})
    for seed in range(20):
        drawn = exam_forms.draw_questions(pool, 60, CCA_F, random.Random(seed))
        assert len({q.id for q in drawn}) == len(drawn)


def test_draw_returns_the_whole_pool_when_it_is_not_bigger_than_the_draw():
    pool = bank({"agentic": 10})
    drawn = exam_forms.draw_questions(pool, 60, CCA_F, random.Random(1))
    assert {q.id for q in drawn} == {q.id for q in pool}


def test_draw_varies_between_attempts():
    """Two sittings of the same exam must not be the same paper."""
    pool = bank({key: 40 for key in CCA_F})
    first = [q.id for q in exam_forms.draw_questions(pool, 60, CCA_F, random.Random(1))]
    second = [q.id for q in exam_forms.draw_questions(pool, 60, CCA_F, random.Random(2))]
    assert first != second


def test_blueprint_naming_an_absent_domain_does_not_shrink_the_paper():
    pool = bank({"agentic": 40, "prompt": 40})
    drawn = exam_forms.draw_questions(pool, 30, CCA_F, random.Random(5))
    assert len(drawn) == 30


def test_draw_without_weights_still_fills_the_paper():
    pool = bank({key: 40 for key in CCA_F})
    drawn = exam_forms.draw_questions(pool, 60, None, random.Random(1))
    assert len(drawn) == 60


def test_questions_with_no_domain_are_still_drawable():
    pool = [FakeQuestion(f"x{i}", None) for i in range(80)]
    drawn = exam_forms.draw_questions(pool, 60, CCA_F, random.Random(1))
    assert len(drawn) == 60


# --- the paper -------------------------------------------------------------


def test_form_round_trips_and_preserves_option_order():
    pool = bank({key: 40 for key in CCA_F})
    evaluation = FakeEvaluation(pool, draw_size=60)
    form = exam_forms.build_form(pool, evaluation, CCA_F, random.Random(11))
    restored = exam_forms.load_form(exam_forms.dump_form(form))
    assert restored == form

    questions = exam_forms.form_questions(restored, evaluation)
    assert len(questions) == 60
    for item, question in zip(restored["items"], questions):
        assert question.id == item["question_id"]
        assert [option.id for option in question.options] == item["option_ids"]


def test_form_questions_without_a_form_returns_the_stored_questions():
    """Every attempt taken before this feature existed still reads back."""
    pool = bank({"agentic": 5})
    evaluation = FakeEvaluation(pool)
    questions = exam_forms.form_questions(None, evaluation)
    assert [q.id for q in questions] == [q.id for q in pool]


def test_a_question_deleted_mid_sitting_does_not_change_the_paper():
    """The paper is what the candidate was shown, not what the bank holds now.

    Skipping a deleted question shortened the paper while the score kept the
    original denominator, so a candidate who answered every remaining question
    correctly scored 50 instead of 100.
    """
    pool = bank({"agentic": 5})
    evaluation = FakeEvaluation(pool)
    form = exam_forms.build_form(pool, evaluation, None, random.Random(1))
    evaluation.questions = pool[:3]
    questions = exam_forms.form_questions(form, evaluation)
    assert len(questions) == 5
    assert all(q.text for q in questions), "a deleted question still renders its stem"


def test_an_option_added_mid_sitting_does_not_appear():
    """An option added after the draw was never on the candidate's paper."""
    pool = bank({"agentic": 1})
    evaluation = FakeEvaluation(pool)
    form = exam_forms.build_form(pool, evaluation, None, random.Random(1))
    pool[0].options.append(FakeOption("late-option"))
    question = exam_forms.form_questions(form, evaluation)[0]
    assert len(question.options) == 4
    assert "late-option" not in [o.id for o in question.options]


def test_editing_an_option_mid_sitting_does_not_change_the_paper():
    pool = bank({"agentic": 1})
    evaluation = FakeEvaluation(pool)
    form = exam_forms.build_form(pool, evaluation, None, random.Random(1))
    shown = [o.text for o in exam_forms.form_questions(form, evaluation)[0].options]
    for option in pool[0].options:
        option.text = "REWRITTEN"
    assert [o.text for o in exam_forms.form_questions(form, evaluation)[0].options] == shown


def test_moving_the_answer_key_mid_sitting_does_not_regrade_the_paper():
    """Grading reads the key the candidate was shown, not the key as it stands."""
    pool = bank({"agentic": 1})
    evaluation = FakeEvaluation(pool)
    form = exam_forms.build_form(pool, evaluation, None, random.Random(1))
    was = [o.id for o in exam_forms.form_questions(form, evaluation)[0].options if o.is_correct]
    for index, option in enumerate(pool[0].options):
        option.is_correct = index == 3
    now = [o.id for o in exam_forms.form_questions(form, evaluation)[0].options if o.is_correct]
    assert now == was


def test_a_stem_edited_mid_sitting_does_not_change_the_paper():
    pool = bank({"agentic": 1})
    evaluation = FakeEvaluation(pool)
    form = exam_forms.build_form(pool, evaluation, None, random.Random(1))
    pool[0].text = "REWRITTEN STEM"
    assert exam_forms.form_questions(form, evaluation)[0].text != "REWRITTEN STEM"


@pytest.mark.parametrize("raw", [None, "", "not json", '{"version": 99, "items": []}', '{"items": "no"}', "[]"])
def test_a_form_that_is_not_a_form_reads_as_absent(raw):
    """A candidate mid-sitting gets their questions, not a 500."""
    assert exam_forms.load_form(raw) is None


def test_options_shuffle_across_attempts():
    pool = bank({"agentic": 1})
    evaluation = FakeEvaluation(pool)
    orders = {
        tuple(exam_forms.build_form(pool, evaluation, None, random.Random(seed))["items"][0]["option_ids"])
        for seed in range(30)
    }
    assert len(orders) > 1


# --- the scale -------------------------------------------------------------


def test_scale_endpoints_and_the_published_cut():
    assert exam_forms.scale_score(0, 60) == 100
    assert exam_forms.scale_score(60, 60) == 1000
    # 720 of 1000 is 42 of 60, which is what the standalone practice app reports.
    assert exam_forms.raw_needed(720, 60) == 42
    assert exam_forms.scale_score(42, 60) >= 720
    assert exam_forms.scale_score(41, 60) < 720


def test_raw_needed_for_the_other_published_form_lengths():
    assert exam_forms.raw_needed(720, 53) == 37
    assert exam_forms.raw_needed(720, 63) == 44


def test_raw_needed_is_the_first_score_that_clears_the_cut():
    for total in (53, 60, 63, 106):
        needed = exam_forms.raw_needed(720, total)
        assert exam_forms.scale_score(needed, total) >= 720
        assert exam_forms.scale_score(needed - 1, total) < 720


def test_scale_of_an_empty_paper_does_not_divide_by_zero():
    assert exam_forms.scale_score(0, 0) == 100
    assert exam_forms.raw_needed(720, 0) == 0


# --- the diagnostic --------------------------------------------------------


def test_domain_breakdown_counts_correct_and_total():
    questions = bank({"agentic": 3, "prompt": 2})
    graded = [(questions[0], True), (questions[1], False), (questions[2], True),
              (questions[3], True), (questions[4], True)]
    rows = {row["key"]: row for row in exam_forms.domain_breakdown(graded)}
    assert rows["agentic"]["correct"] == 2 and rows["agentic"]["total"] == 3
    assert rows["prompt"]["correct"] == 2 and rows["prompt"]["total"] == 2
    assert rows["agentic"]["share"] == pytest.approx(2 / 3)


def test_domain_breakdown_omits_questions_with_no_domain():
    """Naming a domain a candidate cannot go and study is noise, not a diagnostic."""
    rows = exam_forms.domain_breakdown([(FakeQuestion("x", None), True)])
    assert rows == []
