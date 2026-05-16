from interview.core.setup import candidate_package
from interview.relay.store import SessionStore


def test_candidate_package_never_exposes_hm_key():
    payload = {
        "code": "INT-1234-AB",
        "problem": "Build something",
        "rubric": "Private scoring notes",
        "hm_key": "admin-secret",
        "relay_url": "https://relay.example",
        "submit_token": "candidate-submit-token",
        "created_at": 1,
        "problem_hash": "abc123",
    }

    public = candidate_package(payload)

    assert public["submit_token"] == "candidate-submit-token"
    assert "hm_key" not in public
    assert "rubric" not in public


def test_relay_candidate_payload_uses_scoped_submit_token(tmp_path):
    store = SessionStore(tmp_path)
    hm_key = store.register_hm()
    code = "INT-1234-AB"

    store.register_interview(
        hm_key,
        code,
        {
            "code": code,
            "problem": "Build something",
            "rubric": "Private scoring notes",
            "hm_key": hm_key,
            "relay_url": "https://relay.example",
        },
    )

    public = store.get_interview_candidate(hm_key, code)

    assert public is not None
    assert public["code"] == code
    assert public["submit_token"]
    assert "hm_key" not in public
    assert "rubric" not in public
    assert store.verify_submit_token(hm_key, code, public["submit_token"])
    assert not store.verify_submit_token(hm_key, code, "wrong-token")
