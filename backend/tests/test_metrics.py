from eval.metrics import (
    QARowResult,
    QASummary,
    score_qa,
    score_term_consistency,
)


def test_score_qa_normal_hit():
    correct, leaked = score_qa(
        answer="He joined the Azure Wood Sect.",
        gold_contains=["Azure Wood"],
        is_spoiler_probe=False,
    )
    assert correct is True
    assert leaked is False


def test_score_qa_normal_miss():
    correct, leaked = score_qa(
        answer="He joined some other sect entirely.",
        gold_contains=["Azure Wood"],
        is_spoiler_probe=False,
    )
    assert correct is False


def test_score_qa_spoiler_refusal_counts_as_correct():
    correct, leaked = score_qa(
        answer="I don't have information about that yet.",
        gold_contains=["don't have", "cannot", "no information"],
        is_spoiler_probe=True,
    )
    # Spoiler probe: refusal phrase hit -> not leaked
    assert leaked is False


def test_score_qa_spoiler_leak():
    correct, leaked = score_qa(
        answer="Wang Lin reaches Golden Core in chapter 50.",
        gold_contains=["don't have", "cannot", "no information"],
        is_spoiler_probe=True,
    )
    assert leaked is True


def test_term_consistency_perfect():
    s = score_term_consistency(
        source_term="王林",
        expected_target="Wang Lin",
        samples=[
            ("王林来了", "Wang Lin arrived"),
            ("王林笑了", "Wang Lin smiled"),
        ],
    )
    assert s.rate == 1.0


def test_term_consistency_partial():
    s = score_term_consistency(
        source_term="王林",
        expected_target="Wang Lin",
        samples=[
            ("王林来了", "Wang Lin arrived"),
            ("王林笑了", "Wong Lim smiled"),
        ],
    )
    assert s.rate == 0.5


def test_summary_empty_safe():
    s = QASummary.from_rows([])
    assert s.n == 0
    assert s.accuracy == 0.0
    assert s.spoiler_leakage == 0.0
