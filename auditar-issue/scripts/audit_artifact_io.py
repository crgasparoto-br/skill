#!/usr/bin/env python3
"""Transparent JSON artifact loading plus deterministic sharded transport support."""
from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import posixpath
import shutil
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

ARTIFACT_FORMAT = "base64-shards-v1"
COMPRESSION = "gzip"
DEFAULT_THRESHOLD_BYTES = 24 * 1024
DEFAULT_SHARD_BYTES = 12 * 1024
MAX_DECODED_BYTES = 64 * 1024 * 1024


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _normalize_part_path(value: object) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    normalized = posixpath.normpath(raw)
    if not raw or raw.startswith("/") or normalized in {".", ".."} or normalized.startswith("../"):
        raise ValueError(f"invalid artifact part path: {value!r}")
    return normalized


def _resolve_part(manifest_path: Path, relative: str) -> Path:
    root = manifest_path.resolve().parent
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"artifact part escapes manifest directory: {relative}") from exc
    return candidate


def _gunzip_limited(payload: bytes, *, expected_size: int, max_decoded_bytes: int) -> bytes:
    if expected_size < 0 or expected_size > max_decoded_bytes:
        raise ValueError(f"decoded_size exceeds safety limit: {expected_size}")
    out = bytearray()
    with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as stream:
        while True:
            chunk = stream.read(min(65536, max_decoded_bytes + 1 - len(out)))
            if not chunk:
                break
            out.extend(chunk)
            if len(out) > max_decoded_bytes:
                raise ValueError("decoded artifact exceeds safety limit")
    if len(out) != expected_size:
        raise ValueError(f"decoded_size mismatch: expected {expected_size}, got {len(out)}")
    return bytes(out)


def is_transport_manifest(value: object) -> bool:
    return isinstance(value, dict) and value.get("artifact_format") == ARTIFACT_FORMAT


def read_logical_bytes(path: Path, *, max_decoded_bytes: int = MAX_DECODED_BYTES) -> tuple[bytes, dict[str, Any] | None]:
    path = path.resolve()
    physical = path.read_bytes()
    try:
        parsed = json.loads(physical.decode("utf-8"))
    except Exception:
        return physical, None
    if not is_transport_manifest(parsed):
        return physical, None

    manifest = parsed
    if manifest.get("compression") != COMPRESSION:
        raise ValueError(f"unsupported artifact compression: {manifest.get('compression')!r}")
    if manifest.get("schema_version") not in {1, 2}:
        raise ValueError("artifact transport manifest schema_version must be 1 or 2")
    expected_encoded = manifest.get("encoded_size")
    expected_decoded = manifest.get("decoded_size")
    decoded_sha = str(manifest.get("decoded_sha256") or "")
    if not isinstance(expected_encoded, int) or expected_encoded < 1:
        raise ValueError("artifact transport encoded_size must be a positive integer")
    if not isinstance(expected_decoded, int) or expected_decoded < 1:
        raise ValueError("artifact transport decoded_size must be a positive integer")
    if len(decoded_sha) != 64:
        raise ValueError("artifact transport decoded_sha256 must be a SHA-256 digest")
    parts = manifest.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError("artifact transport parts must be a non-empty array")

    encoded_chunks: list[bytes] = []
    seen: set[str] = set()
    for index, item in enumerate(parts):
        if not isinstance(item, dict):
            raise ValueError(f"artifact part {index} must be an object")
        relative = _normalize_part_path(item.get("path"))
        if relative in seen:
            raise ValueError(f"duplicate artifact part path: {relative}")
        seen.add(relative)
        part_path = _resolve_part(path, relative)
        raw = part_path.read_bytes()
        expected_size = item.get("size")
        if not isinstance(expected_size, int) or expected_size < 1:
            raise ValueError(f"artifact part {relative} size must be a positive integer")
        if len(raw) != expected_size:
            raise ValueError(f"artifact part {relative} size mismatch")
        expected_sha = str(item.get("sha256") or "")
        if len(expected_sha) != 64 or sha256_bytes(raw) != expected_sha:
            raise ValueError(f"artifact part {relative} SHA-256 mismatch")
        encoded_chunks.append(raw)

    encoded = b"".join(encoded_chunks)
    if len(encoded) != expected_encoded:
        raise ValueError(f"encoded_size mismatch: expected {expected_encoded}, got {len(encoded)}")
    encoded_sha = str(manifest.get("encoded_sha256") or "")
    if encoded_sha and sha256_bytes(encoded) != encoded_sha:
        raise ValueError("encoded_sha256 mismatch")
    try:
        compressed = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError(f"invalid base64 artifact payload: {exc}") from exc
    decoded = _gunzip_limited(compressed, expected_size=expected_decoded, max_decoded_bytes=max_decoded_bytes)
    if sha256_bytes(decoded) != decoded_sha:
        raise ValueError("decoded_sha256 mismatch")
    return decoded, manifest


def load_json_artifact(path: Path, *, require_object: bool = False) -> Any:
    logical, _ = read_logical_bytes(path)
    try:
        value = json.loads(logical.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"invalid JSON artifact {path}: {exc}") from exc
    if require_object and not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def artifact_metadata(path: Path) -> dict[str, Any]:
    path = path.resolve()
    logical, manifest = read_logical_bytes(path)
    result: dict[str, Any] = {
        "name": path.name,
        "sha256": sha256_file(path),
        "logical_sha256": sha256_bytes(logical),
        "logical_size": len(logical),
    }
    if manifest is None:
        result["artifact_transport"] = {"format": "plain-json", "version": 1}
        return result
    result["artifact_transport"] = {
        "format": ARTIFACT_FORMAT,
        "version": 1,
        "compression": COMPRESSION,
        "encoded_size": manifest["encoded_size"],
        "decoded_size": manifest["decoded_size"],
        "decoded_sha256": manifest["decoded_sha256"],
        "encoded_sha256": manifest.get("encoded_sha256"),
        "parts": [
            {
                "path": _normalize_part_path(item["path"]),
                "size": item["size"],
                "sha256": item["sha256"],
            }
            for item in manifest["parts"]
        ],
    }
    return result


def artifact_relative_paths(path: Path) -> list[str]:
    path = path.resolve()
    _, manifest = read_logical_bytes(path)
    result = [path.name]
    if manifest is not None:
        result.extend(_normalize_part_path(item["path"]) for item in manifest["parts"])
    return result


def _deterministic_gzip(data: bytes) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as stream:
        stream.write(data)
    return buffer.getvalue()


def pack_json_artifact(
    path: Path,
    *,
    threshold_bytes: int = DEFAULT_THRESHOLD_BYTES,
    shard_bytes: int = DEFAULT_SHARD_BYTES,
    force: bool = False,
    artifact_kind: str | None = None,
) -> dict[str, Any]:
    path = path.resolve()
    if threshold_bytes < 1 or shard_bytes < 4:
        raise ValueError("threshold_bytes and shard_bytes must be positive")
    if shard_bytes % 4:
        raise ValueError("shard_bytes must be divisible by 4 for base64 alignment")

    load_json_artifact(path)
    raw, transport = read_logical_bytes(path)
    if transport is not None:
        return artifact_metadata(path)
    if not force and len(raw) <= threshold_bytes:
        return artifact_metadata(path)

    # Validate the logical JSON before replacing the original file.
    json.loads(raw.decode("utf-8"))
    compressed = _deterministic_gzip(raw)
    encoded = base64.b64encode(compressed)
    parts_dir = path.parent / f"{path.stem}.parts"
    temp_dir = path.parent / f".{path.stem}.parts.tmp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)

    parts: list[dict[str, Any]] = []
    for index, offset in enumerate(range(0, len(encoded), shard_bytes)):
        chunk = encoded[offset : offset + shard_bytes]
        name = f"part-{index:03d}.b64"
        part_path = temp_dir / name
        part_path.write_bytes(chunk)
        parts.append({
            "path": f"{path.stem}.parts/{name}",
            "size": len(chunk),
            "sha256": sha256_bytes(chunk),
        })

    manifest = {
        "schema_version": 2,
        "artifact_format": ARTIFACT_FORMAT,
        "artifact_kind": artifact_kind or path.stem,
        "compression": COMPRESSION,
        "encoded_size": len(encoded),
        "encoded_sha256": sha256_bytes(encoded),
        "decoded_size": len(raw),
        "decoded_sha256": sha256_bytes(raw),
        "parts": parts,
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")

    if parts_dir.exists():
        shutil.rmtree(parts_dir)
    temp_dir.replace(parts_dir)
    path.write_bytes(manifest_bytes)

    # Fail closed if the round trip cannot reproduce the exact logical bytes.
    decoded, _ = read_logical_bytes(path)
    if decoded != raw:
        raise RuntimeError("artifact transport round-trip changed logical bytes")
    return artifact_metadata(path)
