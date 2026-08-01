# ADR-6 — Add a short-answer question type, authored upstream

## ADR Metadata

| Field | Value |
|---|---|
| **ADR Number** | ADR-6 |
| **Title** | Add a short-answer question type with instructor grading, authored upstream |
| **Status** | **Proposed** |
| **Date** | 2026-07-28 |
| **Author** | Max Sheahan (curriculum) |
| **Decision needed from** | Repo owner — accept, amend, or reject |
| **Applies** | ADR-1 (`002-AT-ADEC-adopt-and-mature-upstream.md`) |

## 1. Decision Summary

> **We will** add a `short_answer` question type to NOW-LMS evaluations, with
> written-response storage, a per-question rubric, and an instructor grading
> queue, **authored as an upstream contribution to `bmosoluciones/now-lms`**
> under the ADR-1 rule, **in order to** let an evaluation ask a learner to
> explain, predict, or justify rather than only to recognise a correct option,
> **accepting that** an evaluation containing a short-answer question cannot
> return a score at submit time and will hold in a pending-grade state until
> an instructor grades it.

## 2. Context

NOW-LMS evaluations support exactly two question types. `now_lms/forms/__init__.py:129`
defines the full set:

```python
return [("multiple", _l("Opción múltiple")), ("boolean", _l("Verdadero/Falso"))]
```

There is no third type, no storage for a written response, and no rubric
field. `Answer` (`now_lms/db/__init__.py:1067`) persists only
`selected_option_ids`, a JSON array of option UUIDs. `Question` carries `text`
and `explanation`, both instructor-facing, and neither is a grading criterion.

The consequence is that the platform can assess recognition and cannot assess
explanation. A question may ask a learner to pick the correct answer from a
list. It cannot ask a learner to predict what a command will do before running
it, to justify an architectural choice, or to describe what they expect to
break — and then hold that written answer against stated criteria.

That is a general limitation rather than an Intent Solutions one. Every
comparable learning platform ships a short-answer or essay question type, and
its absence here is the single largest gap between what NOW-LMS assesses and
what a practice-based curriculum needs to assess.

The gap is also narrower to close than it looks. The entire grading path is
four functions in one file (`now_lms/vistas/evaluations.py`):
`_answer_is_correct`, `calculate_score`, `_resolve_option_ids`, and
`_save_question_answers`. `Question.type` is `String(20)` with no enumeration
constraint, so a new type value needs no schema change. `EvaluationAttempt.passed`
is already `nullable=True`, so a pending-grade state is representable in the
schema as it stands and is simply never produced today, because
`take_evaluation` scores every attempt synchronously on submit.

## 3. Decision Drivers

| Driver | Weight | Note |
|---|---|---|
| Native-first rule (ADR-1) | High | A generic capability every LMS has belongs upstream, not in a fork patch |
| Sync survival | High | A fork-local question type would conflict on every upstream evaluation change; upstream authorship removes the tax permanently |
| Assessment ceiling | High | Recognition-only assessment caps what any curriculum on this platform can ask |
| Migration risk | Medium | One additive migration, all columns nullable, no backfill, no change to existing rows |
| Blast radius | Medium | Four functions, one form choice list, three templates. Existing question types keep their current code path unchanged |
| Grading throughput | Low-Medium | Manual grading is an instructor cost; accepted for now, see §6 |

## 4. Alternatives Considered

1. **Fake it with multiple choice.** Convert every written prompt into a
   distractor set. Rejected: it changes the cognitive demand. A learner who
   recognises the right prediction among four has not produced one, and the
   production is the point.

2. **Collect written answers outside the platform** (a form, a document, a
   message thread). Rejected: it splits the learner's record across two
   systems, it does not participate in the evaluation attempt model or the
   certificate gate, and it leaves the platform unable to report on the work
   it is supposedly assessing.

3. **Fork-local patch to the evaluation engine.** Rejected under ADR-1. The
   evaluation engine is upstream's most-touched surface; a private divergence
   there is a permanent merge-conflict tax, and the capability is generic
   enough that upstream is the correct home on the merits, not merely by rule.

4. **Upstream contribution (chosen).** Author it against `upstream/main`, PR to
   `bmosoluciones/now-lms`, and carry it in the fork only if and while the
   upstream review is open.

## 5. Proposed Scope

### Schema — one additive migration, all columns nullable

| Table | Column | Type | Purpose |
|---|---|---|---|
| `answer` | `text_response` | Text | The learner's written answer |
| `answer` | `awarded_points` | Float | Score assigned by the grader |
| `answer` | `feedback` | Text | Grader's written response to the learner |
| `answer` | `graded_at` | DateTime | Null until graded |
| `answer` | `graded_by` | FK `usuario` | Who graded it |
| `question` | `rubric` | Text | The criteria the answer is scored against |
| `question` | `max_points` | Float | Defaults to 1.0, preserving current per-question weighting |

`question.type` needs no migration. It is `String(20)` and unconstrained.

### Code

- `_answer_is_correct` becomes `_answer_score(answer) -> float | None`, where
  `None` means not yet graded. Existing `multiple` and `boolean` branches
  return 1.0 or 0.0 and behave exactly as they do today.
- `calculate_score` sums awarded points over `max_points` and returns `None`
  when any answer is ungraded.
- `_save_question_answers` writes `text_response` for the new type.
- `take_evaluation` leaves `passed` as `None` when the attempt holds an
  ungraded answer, rather than stamping pass or fail.
- `forms/__init__.py:129` gains the third choice.

### Templates

Question editor (rubric and points fields, shown for the new type only),
learner view (a textarea in place of the option list, plus grader feedback on
the result page), and a new instructor grading queue.

### Behaviour that must not change

An evaluation containing only `multiple` and `boolean` questions must score,
pass, fail, and issue certificates exactly as it does now. That is the
regression bar for the upstream PR.

## 6. Consequences

**Positive.** Evaluations can assess explanation and prediction, not only
recognition. The rubric becomes a first-class field rather than something an
instructor holds in their head. `EvaluationReopenRequest`, which already
implements request-reopen with instructor approval, becomes usable as a
corrective loop rather than only an appeals path.

**Negative and accepted.** An evaluation containing a short-answer question
cannot return an immediate score, which changes the learner's experience of
that evaluation from instant to deferred. Grading is instructor labour that
scales linearly with enrolment, and at cohort size that is a real operational
cost rather than a rounding error. `can_user_receive_certificate` already
blocks on `passed is not True`, so a pending attempt correctly withholds a
certificate with no change — but it does so silently, and the learner-facing
message for "submitted, awaiting grading" does not exist yet and must be
written.

**Out of scope for this ADR.** Automated grading of written answers is
deliberately excluded. It is a separate decision with its own dependencies —
an external model provider, a cost model, and a revision loop the current
one-shot attempt model does not support — and it should not ride along on a
question-type decision. This ADR neither proposes it nor forecloses it. The
interface described above is sufficient for a grader of any kind to be added
later without a second migration.

## 7. Open Questions for the Reviewer

1. **Upstream first, or fork first?** ADR-1 says upstream. Upstream PR #179 has
   been open and waiting on the maintainer for some time, so upstream-first
   carries real schedule risk for anything that depends on this. Options are to
   accept the wait, or to carry the change on `deploy/now-lms-fixed` while the
   upstream PR is open and drop it on acceptance. The second is a temporary
   divergence rather than a permanent one, but it is still divergence, and
   ADR-1 does not currently describe that case.
2. **Multiple short answers per evaluation.** Permitted, or capped at one, to
   bound grading load?
3. **Partial credit.** The `awarded_points` design supports it. Should the
   grading UI expose a free score, or fixed bands?

## 8. Verification Plan

Not yet built. When it is:

- Existing evaluation tests pass unchanged (the regression bar in §5).
- New tests: a short-answer attempt holds at `passed is None`; a graded
  attempt scores correctly; a mixed evaluation containing all three types
  scores correctly; a certificate is withheld while an attempt is pending and
  issues once it is graded.
- `python dev/lint.sh` clean and `python dev/test.sh` green across the
  SQLite, PostgreSQL, and MySQL paths, per `docs/CONTRIBUTING.md`.
- The migration applied and rolled back against a populated database.

## 9. Related

- ADR-1 (`002-AT-ADEC-adopt-and-mature-upstream.md`) — the rule this applies.
- `001-PP-PROD-now-lms-fork-prd.md` — the baseline this proposes to extend.
- `FORK.md` — upstream contribution conventions and the open PR queue.
