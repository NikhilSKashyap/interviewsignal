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
        "grading_api_key": "sk-ant-secret",
        "created_at": 1,
        "problem_hash": "abc123",
    }

    public = candidate_package(payload)

    assert public["submit_token"] == "candidate-submit-token"
    assert "hm_key" not in public
    assert "rubric" not in public
    assert "grading_api_key" not in public


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


def test_relay_auto_grade_defaults_to_enabled_for_legacy_packages(tmp_path):
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

    assert store.get_auto_grade(hm_key, code) is True


def test_relay_auto_grade_can_be_disabled_explicitly(tmp_path):
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
            "auto_grade": False,
        },
    )

    assert store.get_auto_grade(hm_key, code) is False


def test_relay_stores_grading_api_key_without_exposing_it(tmp_path):
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
            "grading_api_key": "sk-ant-secret",
        },
    )

    public = store.get_interview_candidate(hm_key, code)

    assert store.get_grading_api_key(hm_key, code) == "sk-ant-secret"
    assert public is not None
    assert "grading_api_key" not in public


def test_rubric_update_can_sync_grading_api_key_for_existing_interview(tmp_path):
    store = SessionStore(tmp_path)
    hm_key = store.register_hm()
    code = "INT-1234-AB"

    store.register_interview(
        hm_key,
        code,
        {
            "code": code,
            "problem": "Build something",
            "rubric": "Old rubric",
            "hm_key": hm_key,
            "relay_url": "https://relay.example",
        },
    )

    store.update_rubric(hm_key, code, "New rubric", grading_api_key="sk-ant-secret")

    assert store.get_rubric(hm_key, code) == "New rubric"
    assert store.get_grading_api_key(hm_key, code) == "sk-ant-secret"
    public = store.get_interview_candidate(hm_key, code)
    assert public is not None
    assert "grading_api_key" not in public


def test_retire_interview_makes_code_unfetchable_but_keeps_hm_history(tmp_path):
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

    assert store.lookup_hm_for_code(code) == hm_key
    public = store.get_interview_candidate(hm_key, code)
    assert public is not None

    result = store.retire_interview(hm_key, code)

    assert result["retired"] is True
    assert store.lookup_hm_for_code(code) is None
    assert store.get_interview_candidate(hm_key, code) is None
    assert not store.verify_submit_token(hm_key, code, public["submit_token"])

    interviews = store.list_interviews(hm_key)
    assert interviews[0]["code"] == code
    assert interviews[0]["retired_at"]
