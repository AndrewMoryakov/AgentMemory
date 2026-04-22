from __future__ import annotations

import re
import string
from typing import Any

from agentmemory.providers.base import MemoryRecord


VERB_ALIASES = {
    "like": "likes",
    "likes": "likes",
    "prefer": "prefers",
    "prefers": "prefers",
    "use": "uses",
    "uses": "uses",
    "want": "wants",
    "wants": "wants",
    "need": "needs",
    "needs": "needs",
}


def _clean_text(value: str) -> str:
    normalized = value.strip().lower()
    normalized = normalized.translate(str.maketrans("", "", string.punctuation))
    return " ".join(normalized.split())


def _claim_from_metadata(record: MemoryRecord) -> dict[str, Any] | None:
    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        return None
    key = metadata.get("claim_key") or metadata.get("conflict_key")
    value = metadata.get("claim_value")
    if not isinstance(key, str) or not key.strip() or value is None:
        return None
    polarity = metadata.get("claim_polarity", True)
    if isinstance(polarity, str):
        polarity = polarity.strip().lower() not in {"false", "negative", "not", "no", "0"}
    return {
        "key": _clean_text(key),
        "subject": _clean_text(key),
        "predicate": "metadata_claim",
        "value": _clean_text(str(value)),
        "polarity": bool(polarity),
        "source": "metadata",
    }


def _claim_from_text(record: MemoryRecord) -> dict[str, Any] | None:
    raw = record.get("memory")
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = _clean_text(raw)

    be_match = re.match(r"^(?P<subject>.+?)\s+(?P<verb>is|are|was|were)\s+(?P<neg>not\s+)?(?P<value>.+)$", text)
    if be_match:
        subject = be_match.group("subject")
        value = be_match.group("value")
        return {
            "key": f"{subject}|is",
            "subject": subject,
            "predicate": "is",
            "value": value,
            "polarity": not bool(be_match.group("neg")),
            "source": "text",
        }

    action_match = re.match(
        r"^(?P<subject>.+?)\s+(?:(?P<neg>does not|doesnt|do not|dont)\s+)?(?P<verb>likes|like|prefers|prefer|uses|use|wants|want|needs|need)\s+(?P<value>.+)$",
        text,
    )
    if action_match:
        subject = action_match.group("subject")
        verb = VERB_ALIASES[action_match.group("verb")]
        value = action_match.group("value")
        return {
            "key": f"{subject}|{verb}",
            "subject": subject,
            "predicate": verb,
            "value": value,
            "polarity": not bool(action_match.group("neg")),
            "source": "text",
        }

    return None


def _claim_for_record(record: MemoryRecord) -> dict[str, Any] | None:
    return _claim_from_metadata(record) or _claim_from_text(record)


def _record_summary(record: MemoryRecord) -> dict[str, Any]:
    return {
        "id": record.get("id"),
        "memory": record.get("memory"),
        "metadata": record.get("metadata") if isinstance(record.get("metadata"), dict) else {},
        "user_id": record.get("user_id"),
        "agent_id": record.get("agent_id"),
        "run_id": record.get("run_id"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "provider": record.get("provider"),
    }


def _conflict_reason(left_claim: dict[str, Any], right_claim: dict[str, Any]) -> tuple[str, float] | None:
    if left_claim["key"] != right_claim["key"]:
        return None
    if left_claim["value"] == right_claim["value"] and left_claim["polarity"] != right_claim["polarity"]:
        return "opposite_polarity", 0.95
    if left_claim["value"] != right_claim["value"] and left_claim["polarity"] and right_claim["polarity"]:
        return "different_values_for_same_claim", 0.72
    if left_claim["value"] != right_claim["value"] and left_claim["polarity"] != right_claim["polarity"]:
        return "possibly_related_negation", 0.62
    return None


def find_conflicts(records: list[MemoryRecord]) -> list[dict[str, Any]]:
    claimed: list[tuple[MemoryRecord, dict[str, Any]]] = []
    for record in records:
        claim = _claim_for_record(record)
        if claim is not None:
            claimed.append((record, claim))

    conflicts: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for left_index, (left_record, left_claim) in enumerate(claimed):
        for right_record, right_claim in claimed[left_index + 1 :]:
            reason = _conflict_reason(left_claim, right_claim)
            if reason is None:
                continue
            left_id = str(left_record.get("id") or left_index)
            right_id = str(right_record.get("id") or len(seen_pairs))
            pair_key = tuple(sorted((left_id, right_id)))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            conflicts.append(
                {
                    "reason": reason[0],
                    "confidence": reason[1],
                    "subject": left_claim["subject"],
                    "predicate": left_claim["predicate"],
                    "left_claim": {
                        "value": left_claim["value"],
                        "polarity": left_claim["polarity"],
                        "source": left_claim["source"],
                    },
                    "right_claim": {
                        "value": right_claim["value"],
                        "polarity": right_claim["polarity"],
                        "source": right_claim["source"],
                    },
                    "left": _record_summary(left_record),
                    "right": _record_summary(right_record),
                }
            )

    return sorted(conflicts, key=lambda item: (-float(item["confidence"]), str(item["subject"]), str(item["predicate"])))
