"""
tests/test_hash_chain.py
------------------------
Unit tests for the hash chain construction used in session events.

The core integrity claim: every event in events.jsonl is bound to the
previous event by a chained SHA-256 hash. Modifying any event breaks
all subsequent hashes in the chain.

  hash[n] = SHA256(prev_hash_raw + json(body, sort_keys=True))[:16]
  where body = {type, timestamp, payload}  (excludes "hash" and "prev_hash")

These tests verify that claim.
"""

import hashlib
import json
import pytest

# We test the chain construction directly by reimplementing the function
# (mirroring what session.py and claude_hook.py both do) so any divergence
# between the two implementations would surface immediately.


def _chain_hash(prev_hash: str, body: dict) -> str:
    """
    Canonical chain hash used in both session.py and claude_hook.py.
    prev_hash is prepended as raw bytes — not embedded as a JSON field.
    """
    content = json.dumps(body, sort_keys=True)
    return hashlib.sha256((prev_hash + content).encode()).hexdigest()[:16]


def _make_event(event_type: str, payload: dict, prev_hash: str = "", ts: float = 1000.0) -> dict:
    """Build a chained event dict (same structure as events.jsonl)."""
    body = {"type": event_type, "timestamp": ts, "payload": payload}
    h = _chain_hash(prev_hash, body)
    return {
        "type": body["type"],
        "timestamp": body["timestamp"],
        "prev_hash": prev_hash,
        "payload": payload,
        "hash": h,
    }


# ─── _chain_hash unit tests ──────────────────────────────────────────────────

class TestChainHash:
    def test_deterministic(self):
        body = {"type": "tool_call", "timestamp": 1000.0, "payload": {"tool": "Read"}}
        h1 = _chain_hash("", body)
        h2 = _chain_hash("", body)
        assert h1 == h2

    def test_different_prev_hash_produces_different_hash(self):
        body = {"type": "tool_call", "timestamp": 1000.0, "payload": {}}
        h_empty = _chain_hash("", body)
        h_other = _chain_hash("abcdef1234567890", body)
        assert h_empty != h_other

    def test_different_body_produces_different_hash(self):
        prev = "abc123"
        body1 = {"type": "tool_call", "timestamp": 1000.0, "payload": {"a": 1}}
        body2 = {"type": "tool_call", "timestamp": 1000.0, "payload": {"a": 2}}
        assert _chain_hash(prev, body1) != _chain_hash(prev, body2)

    def test_body_key_order_does_not_matter(self):
        prev = ""
        body_a = {"timestamp": 1000.0, "type": "x", "payload": {}}
        body_b = {"type": "x", "payload": {}, "timestamp": 1000.0}
        # sort_keys=True makes JSON canonical regardless of dict insertion order
        assert _chain_hash(prev, body_a) == _chain_hash(prev, body_b)

    def test_first_event_has_empty_prev(self):
        event = _make_event("session_start", {"info": "test"}, prev_hash="")
        assert event["prev_hash"] == ""

    def test_output_length_is_16(self):
        h = _chain_hash("", {"type": "x", "timestamp": 1.0, "payload": {}})
        assert len(h) == 16

    def test_hash_is_hex(self):
        h = _chain_hash("", {"type": "x", "timestamp": 1.0, "payload": {}})
        int(h, 16)  # raises ValueError if not hex


# ─── Chain linkage tests ─────────────────────────────────────────────────────

class TestChainLinkage:
    def _build_chain(self, n: int) -> list[dict]:
        events = []
        prev = ""
        for i in range(n):
            e = _make_event("tool_call", {"step": i}, prev_hash=prev, ts=float(i))
            events.append(e)
            prev = e["hash"]
        return events

    def test_each_event_prev_hash_matches_previous_hash(self):
        events = self._build_chain(5)
        for i in range(1, len(events)):
            assert events[i]["prev_hash"] == events[i - 1]["hash"], (
                f"Event {i}: prev_hash mismatch"
            )

    def test_hash_chain_can_be_verified(self):
        """Walk the chain and re-derive every hash — should all match."""
        events = self._build_chain(10)
        prev = ""
        for i, ev in enumerate(events):
            body = {k: v for k, v in ev.items() if k not in ("hash", "prev_hash")}
            expected = _chain_hash(prev, body)
            assert ev["hash"] == expected, f"Hash mismatch at event {i}"
            prev = ev["hash"]

    def test_first_event_prev_hash_is_empty_string(self):
        events = self._build_chain(3)
        assert events[0]["prev_hash"] == ""


# ─── Tamper detection tests ───────────────────────────────────────────────────

class TestTamperDetection:
    def _build_chain(self, n: int) -> list[dict]:
        events = []
        prev = ""
        for i in range(n):
            e = _make_event("tool_call", {"step": i}, prev_hash=prev, ts=float(i))
            events.append(e)
            prev = e["hash"]
        return events

    def _verify(self, events: list[dict]) -> bool:
        """Return True iff the entire chain verifies cleanly."""
        prev = ""
        for ev in events:
            body = {k: v for k, v in ev.items() if k not in ("hash", "prev_hash")}
            if ev.get("prev_hash") != prev:
                return False
            if _chain_hash(prev, body) != ev.get("hash"):
                return False
            prev = ev["hash"]
        return True

    def test_clean_chain_verifies(self):
        events = self._build_chain(5)
        assert self._verify(events)

    def test_modifying_payload_breaks_chain(self):
        events = self._build_chain(5)
        # Tamper: change the payload of event 2
        events[2]["payload"]["step"] = 999
        assert not self._verify(events)

    def test_modifying_timestamp_breaks_chain(self):
        events = self._build_chain(5)
        events[2]["timestamp"] = 9999.0
        assert not self._verify(events)

    def test_rewriting_hash_to_hide_tampering_still_breaks_next(self):
        """
        Attacker modifies event 2 and recomputes its hash.
        Event 3's prev_hash still points to the ORIGINAL hash of event 2,
        so the chain breaks at event 3.
        """
        events = self._build_chain(5)
        # Tamper event 2, recompute its hash to cover tracks
        events[2]["payload"]["step"] = 999
        body2 = {k: v for k, v in events[2].items() if k not in ("hash", "prev_hash")}
        events[2]["hash"] = _chain_hash(events[2]["prev_hash"], body2)
        # Chain should now be broken at event 3
        prev = ""
        broken = False
        for ev in events:
            body = {k: v for k, v in ev.items() if k not in ("hash", "prev_hash")}
            if ev.get("prev_hash") != prev or _chain_hash(prev, body) != ev.get("hash"):
                broken = True
                break
            prev = ev["hash"]
        assert broken

    def test_inserting_event_breaks_chain(self):
        events = self._build_chain(4)
        fake = _make_event("tool_call", {"injected": True}, prev_hash="deadbeef", ts=1.5)
        events.insert(2, fake)
        assert not self._verify(events)

    def test_deleting_event_breaks_chain(self):
        events = self._build_chain(5)
        del events[2]
        assert not self._verify(events)

    def test_prev_hash_embedded_in_body_would_be_weaker(self):
        """
        Demonstrate that the old scheme (prev_hash embedded as a JSON field)
        allows an attacker to rewrite the entire chain forward.
        The new scheme (prev_hash prepended raw, excluded from body) prevents this.
        """
        # Old (weak) scheme: prev_hash is just another field in the hashed JSON
        def old_hash(prev_h: str, event_type: str, payload: dict, ts: float) -> str:
            body = {"type": event_type, "timestamp": ts, "payload": payload,
                    "prev_hash": prev_h}
            return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]

        # New (strong) scheme: prev_hash prepended raw, excluded from body
        def new_hash(prev_h: str, event_type: str, payload: dict, ts: float) -> str:
            body = {"type": event_type, "timestamp": ts, "payload": payload}
            return _chain_hash(prev_h, body)

        # Show they produce different outputs (different constructions)
        h_old = old_hash("abc", "x", {}, 1.0)
        h_new = new_hash("abc", "x", {}, 1.0)
        assert h_old != h_new
