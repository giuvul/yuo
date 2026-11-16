"""Exercise-type plugins: rules, learner views without keys, grading, shuffling."""

import json

import pytest

from tests import fakes
from yuo.assessment import types as xt


@pytest.mark.parametrize("key", sorted(xt.TYPES))
def test_each_type_validates_its_draft_and_hides_its_key(key: str) -> None:
    t = xt.get(key)
    payload = fakes.draft_for(key, "o.1")
    draft = t.Draft.model_validate(payload)
    assert t.rules(draft, {"o.1"}) == []
    assert "objective_code" in " ".join(t.rules(draft, {"other"}))
    view = json.dumps(t.view(payload, seed="s"))
    for secret in ("answer", "answers", "blanks", "model_answer", "rubric", "back"):
        assert f'"{secret}"' not in view, (key, secret)
    t.blind_model().model_json_schema()


def test_grading_of_each_type() -> None:
    assert xt.get("mcq").grade(fakes.item(), "b") == 1.0
    assert xt.get("multi").grade(fakes.draft_for("multi", "o"), ["b", "a"]) == 1.0
    assert xt.get("multi").grade(fakes.draft_for("multi", "o"), ["a"]) == 0.0
    cloze = fakes.draft_for("cloze", "o")
    assert (
        xt.get("cloze").grade(cloze, ["Inner Join"]) == 1.0 and xt.get("cloze").grade(cloze, ["outer"]) == 0.0
    )
    assert xt.get("ordering").grade(fakes.draft_for("ordering", "o"), ["a", "b", "c"]) == 1.0
    m = fakes.draft_for("matching", "o")
    half = [{"left": "INNER", "right": "matches only"}, {"left": "LEFT", "right": "all rows"}]
    assert xt.get("matching").grade(m, half) == pytest.approx(1 / 3)
    assert xt.get("flashcard").grade(fakes.draft_for("flashcard", "o"), 4) == 1.0
    with pytest.raises(ValueError):
        xt.get("flashcard").grade(fakes.draft_for("flashcard", "o"), 7)
    assert xt.get("short_answer").grade(fakes.draft_for("short_answer", "o"), "x") is None


def test_rules_catch_broken_drafts() -> None:
    bad_cloze = {"text": "A {{2}} join", "blanks": [{"n": 1, "answers": ["inner"]}], "objective_code": "o"}
    assert xt.get("cloze").own_rules(xt.ClozeDraft.model_validate(bad_cloze))
    dup = fakes.item()
    dup["options"][1]["text"] = "FROM"
    assert "same text" in " ".join(xt.get("mcq").own_rules(xt.McqDraft.model_validate(dup)))
    leak = xt.Support(hints=["It is the SELECT list.", "x", "y"], solution="s", explanations=[])
    assert "hint 1 gives the answer away" in xt.get("mcq").support_rules(fakes.item(), leak)


def test_ordering_view_is_shuffled_and_stable() -> None:
    p = fakes.draft_for("ordering", "o")
    v1, v2 = xt.get("ordering").view(p, "seed"), xt.get("ordering").view(p, "seed")
    assert v1 == v2 and [s["id"] for s in v1["steps"]] != ["a", "b", "c"]


def test_shuffle_moves_the_key_and_keeps_explanations_with_their_options() -> None:
    t = xt.get("mcq")
    payload = fakes.item(answer="a")
    sup = xt.Support(
        hints=["1", "2", "3"],
        solution="s",
        explanations=[xt.OptionWhy(id=i, why=f"because {i}") for i in "abcd"],
    )
    keys = set()
    for seed in "abcdefgh":
        new, new_sup = xt.shuffle_choices(t, payload, sup, seed)
        assert next(o["text"] for o in new["options"] if o["id"] == new["answer"]) == "FROM"
        assert next(e.why for e in new_sup.explanations if e.id == new["answer"]) == "because a"
        keys.add(new["answer"])
    assert len(keys) > 1


def test_rubric_score_weights_criteria() -> None:
    p = fakes.draft_for("short_answer", "o")
    assert xt.rubric_score(p, xt.RubricGrade(met=[True, False], rationale="r")) == pytest.approx(2 / 3)
