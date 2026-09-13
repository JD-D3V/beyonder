from app.graph.resumable import plan_resume


def test_fresh_start_when_no_progress():
    start, acc, done = plan_resume(
        existing_done=None, existing_text="", total=6, already_complete=False
    )
    assert (start, acc, done) == (0, "", False)


def test_resumes_from_saved_piece_with_prefix():
    start, acc, done = plan_resume(
        existing_done=3, existing_text="one\n\ntwo\n\nthree",
        total=6, already_complete=False,
    )
    assert start == 3
    assert acc == "one\n\ntwo\n\nthree"
    assert done is False


def test_complete_short_circuits_and_never_retranslates():
    start, acc, done = plan_resume(
        existing_done=None, existing_text="full translation",
        total=6, already_complete=True,
    )
    assert done is True
    assert start == 6  # reported as all pieces done


def test_stale_marker_past_end_restarts():
    # Source was re-imported shorter, leaving pieces_done beyond the new count.
    start, acc, done = plan_resume(
        existing_done=8, existing_text="stale", total=6, already_complete=False
    )
    assert (start, acc, done) == (0, "", False)


def test_zero_pieces_done_keeps_empty_prefix():
    start, acc, done = plan_resume(
        existing_done=0, existing_text="", total=6, already_complete=False
    )
    assert (start, acc, done) == (0, "", False)
