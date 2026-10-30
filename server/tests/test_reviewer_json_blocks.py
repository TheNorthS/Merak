"""Byte reconstruction proves reviewer deduplication retains all scientific tokens."""

import hashlib
import re

import pytest

from server.services.reviewer_json_blocks import reference_repeated_json
from server.services.reviewer_json_compaction import compact_json_evidence
from server.services.review_evidence_packet import build_managed_evidence_packet


def restore(encoded):
    if not encoded.startswith(b"LOSSLESS_JSON_BLOCKS_V1\n"):
        return encoded
    cursor, blocks = encoded.index(b"\nBLOCK ") + 1, {}
    while encoded[cursor:].startswith(b"BLOCK "):
        end = encoded.index(b"\n", cursor)
        _, token, size = encoded[cursor:end].split()
        start = end + 1
        blocks[token] = encoded[start:start + int(size)]
        cursor = start + int(size) + 1
    assert encoded[cursor:cursor + 5] == b"BODY\n"
    return re.sub(rb"@MERAK_JSON_BLOCK_\d+@", lambda match: blocks[match.group()], encoded[cursor + 5:])


@pytest.mark.parametrize("block", [
    b'{"x":1.0000,"x":2e-06,"integer":900719925474099312345,"items":[' + b'1,' * 700 + b'2]}',
    ('{"text":"引号 \\" [ ] { } \\\\ 与换行\\n' + '证据 ' * 600 + '"}').encode(),
])
def test_reconstruction_retains_duplicate_keys_numbers_unicode_and_escapes(block):
    raw = b'{"one":' + block + b',"two":' + block + b'}'
    encoded = reference_repeated_json(raw)
    assert len(encoded) < len(raw)
    assert restore(encoded) == raw


def test_nested_and_partially_shared_objects_round_trip_without_recursive_references():
    inner = b'[' + b'1.0000,' * 400 + b'2e-06]'
    outer = b'{"inner":' + inner + b',"extra":[' + b'3,' * 100 + b'4]}'
    raw = b'[' + outer + b',' + outer + b',' + inner + b']'
    assert restore(reference_repeated_json(raw)) == raw
    assert reference_repeated_json(raw) == reference_repeated_json(raw)


@pytest.mark.parametrize("raw", [b'{invalid}', b'{"x":[1,2]}', b'{"x":"@MERAK_JSON_BLOCK_0@"}', b'\xff'])
def test_invalid_small_or_reserved_content_stays_unchanged(raw):
    assert reference_repeated_json(raw) == raw


def test_complete_packet_fits_budget_without_changing_source_identity(tmp_path):
    block = b'[' + b'1.0000,' * 1000 + b'2e-06]'
    raw = b'{\n"a":' + block + b',\n"b":' + block + b'}'
    path = tmp_path / 'evidence.json'
    path.write_bytes(raw)
    encoded = reference_repeated_json(compact_json_evidence(path.name, raw))
    packet, meta = build_managed_evidence_packet(tmp_path, [path], maximum_files=1,
        maximum_bytes=len(encoded), maximum_file_bytes=len(encoded))
    assert not meta['truncated_paths']
    assert 'lossless_json_blocks_v1' in packet
    assert meta['file_sha256'][path.name] == hashlib.sha256(raw).hexdigest()
    assert path.read_bytes() == raw
    assert restore(encoded) == compact_json_evidence(path.name, raw)


def test_nonidentical_blocks_are_not_merged():
    one = b'[' + b'1.0000,' * 400 + b'2]'
    two = b'[' + b'1.0001,' * 400 + b'2]'
    raw = b'[' + one + b',' + two + b']'
    assert reference_repeated_json(raw) == raw
