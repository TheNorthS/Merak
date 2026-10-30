"""Request compaction preserves duplicate keys, numeric lexemes and string contents."""

import json

from server.services.reviewer_json_compaction import compact_json_evidence
from server.services.review_evidence_packet import build_managed_evidence_packet


def test_only_json_insignificant_whitespace_is_removed():
    raw = b'{\n "x": 1.0000, "large": 900719925474099312345, "x": 2e-06, "text": " a  b \\"q\\" "\n}'
    compact = compact_json_evidence("source.json", raw)
    assert b'1.0000' in compact and b'900719925474099312345' in compact and b'2e-06' in compact
    assert compact.count(b'"x"') == 2 and json.loads(compact) == json.loads(raw)
    assert b' a  b ' in compact


def test_packet_retains_raw_hash_and_complete_compacted_fields(tmp_path):
    import hashlib
    path = tmp_path / "source.json"
    raw = b'{\n  "evidence": [1, 2, 3],\n  "limit": "not measured"\n}'
    path.write_bytes(raw)
    packet, meta = build_managed_evidence_packet(tmp_path, [path], maximum_files=2, maximum_bytes=1000, maximum_file_bytes=1000)
    assert meta["file_sha256"]["source.json"] == hashlib.sha256(raw).hexdigest()
    assert not meta["truncated_paths"]
    assert '"evidence":[1,2,3]' in packet and '"limit":"not measured"' in packet
    assert "json_whitespace_compacted" in packet and path.read_bytes() == raw


def test_invalid_json_and_non_json_evidence_are_not_repaired_or_changed():
    assert compact_json_evidence("invalid.json", b'{ x: 1 }') == b'{ x: 1 }'
    assert compact_json_evidence("code.py", b'{ "x": 1 }') == b'{ "x": 1 }'
