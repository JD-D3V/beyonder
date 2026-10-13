from app.common.logging import _redact


def test_self_referencing_dict_does_not_recurse_forever():
    d = {"a": 1}
    d["self"] = d
    out = _redact(d)
    assert out["a"] == 1
    assert "self" in out


def test_self_referencing_list_and_secret_still_redacted():
    lst = []
    lst.append(lst)
    assert isinstance(_redact(lst), list)
    assert _redact({"api_key": "x"}) == {"api_key": "***"}
