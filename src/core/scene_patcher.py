"""Safe binary patcher for FF7 Steam Edition scene.bin (100% drop rate & backup/restore)."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import struct
import zlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BLOCK_SIZE = 0x2000  # 8192 bytes per scene.bin block
HEADER_POINTER_COUNT = 16
HEADER_SIZE = HEADER_POINTER_COUNT * 4  # 64 bytes
SCENE_RAW_SIZE = 7808  # 0x1E80 bytes per decompressed battle scene

ENEMY_SLOTS_PER_SCENE = 3
ENEMY_DATA_OFFSET = 0x0298
ENEMY_RECORD_SIZE = 0xB8  # 184 bytes
ENEMY_ITEM_RATES_OFFSET = 0x88  # 4 bytes
ENEMY_ITEM_IDS_OFFSET = 0x8C  # 4 x uint16 (8 bytes)

DROP_RATE_100 = 63  # 0x3F -> Rnd(0..63) <= 63 => (63+1)/64 = 100%
STEAL_FLAG = 0x80
STEAL_RATE_100 = 0xBF  # 0x80 | 63 = 191


class ScenePatchError(Exception):
    """Base error raised for scene.bin parsing, patching, or backup failures."""


class BlockOverflowError(ScenePatchError):
    """Raised when a recompressed scene.bin block exceeds 8192 bytes."""


@dataclass(frozen=True)
class DropPatchConfig:
    """Configuration options for patching enemy item drop/steal rates."""

    drop_100: bool = True
    rare_first: bool = True
    steal_100: bool = False

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> DropPatchConfig | None:
        if not isinstance(data, dict):
            return None
        return cls(
            drop_100=bool(data.get("drop_100", True)),
            rare_first=bool(data.get("rare_first", True)),
            steal_100=bool(data.get("steal_100", False)),
        )


@dataclass(frozen=True)
class SceneStats:
    """Summary statistics extracted from a scene.bin file."""

    block_count: int
    scene_count: int
    enemy_slot_count: int
    drop_slot_count: int
    non_max_drop_slot_count: int
    multi_drop_enemy_count: int
    steal_slot_count: int
    non_max_steal_slot_count: int
    sha256: str


@dataclass(frozen=True)
class PatchStatus:
    """Current patch and backup status for one language's scene.bin."""

    exists: bool
    state: str  # "VANILLA" | "PATCHED" | "UNKNOWN_MODIFIED" | "MISSING"
    has_backup: bool
    backup_sha256: str | None
    applied_config: DropPatchConfig | None
    stats: SceneStats | None
    scene_path: Path


def sha256_bytes(data: bytes) -> str:
    """Return lowercase hex SHA-256 digest of bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """Return lowercase hex SHA-256 digest of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write_bytes(target_path: Path, data: bytes) -> None:
    """Write bytes atomically via a sibling temporary file and os.replace."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_name(f"{target_path.name}.{os.getpid()}.tmp")
    try:
        with tmp_path.open("wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if tmp_path.stat().st_size != len(data):
            raise ScenePatchError(f"書き込みサイズ検証に失敗しました: {target_path}")
        os.replace(tmp_path, target_path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def _atomic_write_json(target_path: Path, payload: dict[str, Any]) -> None:
    """Write JSON payload atomically with UTF-8 encoding."""
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _atomic_write_bytes(target_path, encoded)


def unpack_scene_bin(data: bytes) -> list[list[bytes]]:
    """Unpack scene.bin bytes into blocks of decompressed 7808-byte scenes.

    Uses zlib.decompressobj(16 + zlib.MAX_WBITS) instead of gzip.decompress because
    trailing 0xFF padding bytes in a block slice cause gzip.decompress to fail.
    """
    if len(data) == 0 or len(data) % BLOCK_SIZE != 0:
        raise ScenePatchError(
            f"不正な scene.bin サイズです: {len(data)} bytes (8192の倍数である必要があります)"
        )

    block_count = len(data) // BLOCK_SIZE
    blocks: list[list[bytes]] = []

    for block_idx in range(block_count):
        block = data[block_idx * BLOCK_SIZE : (block_idx + 1) * BLOCK_SIZE]
        ptrs = struct.unpack_from("<16I", block, 0)
        valid_ptrs: list[int] = []
        seen_end = False
        for ptr in ptrs:
            if ptr == 0xFFFFFFFF:
                seen_end = True
                continue
            if seen_end:
                raise ScenePatchError(
                    f"ブロック {block_idx} のポインタテーブルに不正な隙間があります。"
                )
            valid_ptrs.append(ptr)

        scenes_in_block: list[bytes] = []
        prev_offset = HEADER_SIZE
        for i, ptr in enumerate(valid_ptrs):
            start = ptr * 4
            end = valid_ptrs[i + 1] * 4 if i + 1 < len(valid_ptrs) else BLOCK_SIZE
            if start < prev_offset or end > BLOCK_SIZE or start >= end:
                raise ScenePatchError(
                    f"ブロック {block_idx} シーン {i} のオフセット範囲が不正です ({start}..{end})。"
                )
            prev_offset = end
            chunk = block[start:end]
            try:
                raw = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(chunk)
            except zlib.error as exc:
                raise ScenePatchError(
                    f"ブロック {block_idx} シーン {i} のgzip解凍に失敗しました: {exc}"
                ) from exc
            if len(raw) != SCENE_RAW_SIZE:
                raise ScenePatchError(
                    f"ブロック {block_idx} シーン {i} の展開サイズ異常: {len(raw)} bytes"
                )
            scenes_in_block.append(raw)

        blocks.append(scenes_in_block)

    return blocks


def pack_scene_bin(blocks: list[list[bytes]]) -> bytes:
    """Repack scene blocks into scene.bin bytes preserving block boundaries."""
    if not blocks:
        raise ScenePatchError("空のブロックリストはパックできません。")

    out_blocks: list[bytes] = []
    for block_idx, scenes_in_block in enumerate(blocks):
        if len(scenes_in_block) > HEADER_POINTER_COUNT:
            raise ScenePatchError(
                f"ブロック {block_idx} のシーン数が上限(16)を超えています: {len(scenes_in_block)}"
            )

        offset = HEADER_SIZE
        ptrs: list[int] = []
        chunks: list[bytes] = []

        for scene_idx, raw in enumerate(scenes_in_block):
            if len(raw) != SCENE_RAW_SIZE:
                raise ScenePatchError(
                    f"ブロック {block_idx} シーン {scene_idx} の生データサイズが不正です: {len(raw)}"
                )
            if offset % 4 != 0:
                raise ScenePatchError(f"内部アライメント異常: offset={offset}")

            ptrs.append(offset // 4)
            comp = gzip.compress(raw, compresslevel=9, mtime=0)
            pad_len = (4 - (len(comp) % 4)) % 4
            padded_chunk = comp + (b"\xff" * pad_len)
            offset += len(padded_chunk)
            if offset > BLOCK_SIZE:
                raise BlockOverflowError(
                    f"ブロック {block_idx} が8192バイトを超過しました ({offset} bytes)。"
                )
            chunks.append(padded_chunk)

        while len(ptrs) < HEADER_POINTER_COUNT:
            ptrs.append(0xFFFFFFFF)

        header = struct.pack("<16I", *ptrs)
        body = b"".join(chunks)
        tail_pad = b"\xff" * (BLOCK_SIZE - offset)
        block_bytes = header + body + tail_pad
        if len(block_bytes) != BLOCK_SIZE:
            raise ScenePatchError(f"ブロック {block_idx} 構築サイズ異常: {len(block_bytes)}")
        out_blocks.append(block_bytes)

    return b"".join(out_blocks)


def _patch_single_scene(raw: bytes, config: DropPatchConfig) -> tuple[bytes, dict[str, int]]:
    """Patch one 7808-byte decompressed scene record and return updated bytes + counters."""
    buf = bytearray(raw)
    eids = struct.unpack_from("<3H", buf, 0)
    counters = {
        "enemies_modified": 0,
        "drop_slots_updated": 0,
        "steal_slots_updated": 0,
        "enemies_reordered": 0,
    }

    for eidx in range(ENEMY_SLOTS_PER_SCENE):
        if eids[eidx] == 0xFFFF:
            continue

        base = ENEMY_DATA_OFFSET + eidx * ENEMY_RECORD_SIZE
        orig_rates = list(buf[base + ENEMY_ITEM_RATES_OFFSET : base + ENEMY_ITEM_RATES_OFFSET + 4])
        orig_items = list(struct.unpack_from("<4H", buf, base + ENEMY_ITEM_IDS_OFFSET))

        new_rates = list(orig_rates)
        new_items = list(orig_items)

        if config.drop_100 and config.rare_first:
            drops: list[tuple[int, int, int]] = []
            steals: list[tuple[int, int, int]] = []
            for idx, (rate, item_id) in enumerate(zip(orig_rates, orig_items)):
                if item_id == 0xFFFF or rate == 0xFF:
                    continue
                if rate < STEAL_FLAG:
                    drops.append((idx, rate, item_id))
                else:
                    steals.append((idx, rate, item_id))

            # Sort rarest (lowest original drop rate) first; stable on ties via idx
            sorted_drops = sorted(drops, key=lambda entry: (entry[1], entry[0]))
            if [entry[2] for entry in sorted_drops] != [entry[2] for entry in drops]:
                counters["enemies_reordered"] += 1

            merged: list[tuple[int, int]] = []
            for _, orig_r, item_id in sorted_drops:
                if orig_r != DROP_RATE_100:
                    counters["drop_slots_updated"] += 1
                merged.append((DROP_RATE_100, item_id))

            for _, orig_r, item_id in steals:
                target_r = STEAL_RATE_100 if config.steal_100 else orig_r
                if target_r != orig_r:
                    counters["steal_slots_updated"] += 1
                merged.append((target_r, item_id))

            while len(merged) < 4:
                merged.append((0xFF, 0xFFFF))

            for slot, (rate_val, item_val) in enumerate(merged[:4]):
                new_rates[slot] = rate_val
                new_items[slot] = item_val
        else:
            for slot in range(4):
                item_id = orig_items[slot]
                rate = orig_rates[slot]
                if item_id == 0xFFFF or rate == 0xFF:
                    continue
                if rate < STEAL_FLAG:
                    if config.drop_100 and rate != DROP_RATE_100:
                        new_rates[slot] = DROP_RATE_100
                        counters["drop_slots_updated"] += 1
                else:
                    if config.steal_100 and rate != STEAL_RATE_100:
                        new_rates[slot] = STEAL_RATE_100
                        counters["steal_slots_updated"] += 1

        if new_rates != orig_rates or new_items != orig_items:
            buf[base + ENEMY_ITEM_RATES_OFFSET : base + ENEMY_ITEM_RATES_OFFSET + 4] = bytes(new_rates)
            struct.pack_into("<4H", buf, base + ENEMY_ITEM_IDS_OFFSET, *new_items)
            counters["enemies_modified"] += 1

    return bytes(buf), counters


def patch_scene_bytes(data: bytes, config: DropPatchConfig) -> tuple[bytes, dict[str, int]]:
    """Patch all scenes in scene.bin bytes and self-verify round-trip decompression."""
    blocks = unpack_scene_bin(data)
    summary = {
        "blocks_count": len(blocks),
        "scenes_count": 0,
        "scenes_modified": 0,
        "enemies_modified": 0,
        "drop_slots_updated": 0,
        "steal_slots_updated": 0,
        "enemies_reordered": 0,
    }

    patched_blocks: list[list[bytes]] = []
    for scene_list in blocks:
        patched_list: list[bytes] = []
        for raw in scene_list:
            summary["scenes_count"] += 1
            patched_raw, c = _patch_single_scene(raw, config)
            if patched_raw != raw:
                summary["scenes_modified"] += 1
            summary["enemies_modified"] += c["enemies_modified"]
            summary["drop_slots_updated"] += c["drop_slots_updated"]
            summary["steal_slots_updated"] += c["steal_slots_updated"]
            summary["enemies_reordered"] += c["enemies_reordered"]
            patched_list.append(patched_raw)
        patched_blocks.append(patched_list)

    out_bytes = pack_scene_bin(patched_blocks)

    # Round-trip self-verification to guarantee zero corruption
    verified_blocks = unpack_scene_bin(out_bytes)
    if [len(b) for b in verified_blocks] != [len(b) for b in patched_blocks]:
        raise ScenePatchError("再圧縮後のラウンドトリップ検証でシーン構成が一致しませんでした。")

    return out_bytes, summary


def inspect_scene_bytes(data: bytes) -> SceneStats:
    """Inspect a scene.bin byte stream and return structural & drop statistics."""
    blocks = unpack_scene_bin(data)
    scene_count = 0
    enemy_slot_count = 0
    drop_slot_count = 0
    non_max_drop_slot_count = 0
    multi_drop_enemy_count = 0
    steal_slot_count = 0
    non_max_steal_slot_count = 0

    for scene_list in blocks:
        for raw in scene_list:
            scene_count += 1
            eids = struct.unpack_from("<3H", raw, 0)
            for eidx in range(ENEMY_SLOTS_PER_SCENE):
                if eids[eidx] == 0xFFFF:
                    continue
                enemy_slot_count += 1
                base = ENEMY_DATA_OFFSET + eidx * ENEMY_RECORD_SIZE
                rates = raw[base + ENEMY_ITEM_RATES_OFFSET : base + ENEMY_ITEM_RATES_OFFSET + 4]
                items = struct.unpack_from("<4H", raw, base + ENEMY_ITEM_IDS_OFFSET)
                drops_for_enemy = 0
                for rate, item_id in zip(rates, items):
                    if item_id == 0xFFFF or rate == 0xFF:
                        continue
                    if rate < STEAL_FLAG:
                        drop_slot_count += 1
                        drops_for_enemy += 1
                        if rate != DROP_RATE_100:
                            non_max_drop_slot_count += 1
                    else:
                        steal_slot_count += 1
                        if rate != STEAL_RATE_100:
                            non_max_steal_slot_count += 1
                if drops_for_enemy > 1:
                    multi_drop_enemy_count += 1

    return SceneStats(
        block_count=len(blocks),
        scene_count=scene_count,
        enemy_slot_count=enemy_slot_count,
        drop_slot_count=drop_slot_count,
        non_max_drop_slot_count=non_max_drop_slot_count,
        multi_drop_enemy_count=multi_drop_enemy_count,
        steal_slot_count=steal_slot_count,
        non_max_steal_slot_count=non_max_steal_slot_count,
        sha256=sha256_bytes(data),
    )


def _backup_paths(backup_dir: Path, lang: str) -> tuple[Path, Path]:
    return (
        backup_dir / f"lang-{lang}_scene.bin.orig",
        backup_dir / f"lang-{lang}_meta.json",
    )


def _load_meta(meta_path: Path) -> dict[str, Any]:
    if not meta_path.is_file():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def get_patch_status(scene_path: Path, backup_dir: Path, lang: str) -> PatchStatus:
    """Return current PatchStatus for the specified language's scene.bin."""
    orig_path, meta_path = _backup_paths(backup_dir, lang)
    meta = _load_meta(meta_path)
    has_backup = orig_path.is_file()
    backup_sha = meta.get("original_sha256")
    if has_backup and not backup_sha:
        try:
            backup_sha = sha256_file(orig_path)
        except OSError:
            backup_sha = None

    if not scene_path.is_file():
        return PatchStatus(
            exists=False,
            state="MISSING",
            has_backup=has_backup,
            backup_sha256=backup_sha,
            applied_config=None,
            stats=None,
            scene_path=scene_path,
        )

    current_bytes = scene_path.read_bytes()
    stats = inspect_scene_bytes(current_bytes)
    current_sha = stats.sha256
    applied_cfg = DropPatchConfig.from_dict(meta.get("applied_config"))

    if has_backup and backup_sha:
        if current_sha == backup_sha:
            state = "VANILLA"
            applied_cfg = None
        elif meta.get("patched_sha256") and current_sha == meta.get("patched_sha256"):
            state = "PATCHED"
        else:
            state = "UNKNOWN_MODIFIED"
            applied_cfg = None
    else:
        if stats.drop_slot_count > 0 and stats.non_max_drop_slot_count == 0:
            state = "UNKNOWN_MODIFIED"
        else:
            state = "VANILLA"
        applied_cfg = None

    return PatchStatus(
        exists=True,
        state=state,
        has_backup=has_backup,
        backup_sha256=backup_sha,
        applied_config=applied_cfg,
        stats=stats,
        scene_path=scene_path,
    )


def apply_drop_patch(
    scene_path: Path,
    backup_dir: Path,
    lang: str,
    config: DropPatchConfig,
) -> PatchStatus:
    """Back up original scene.bin (if not already backed up) and apply drop patch atomically."""
    if not scene_path.is_file():
        raise ScenePatchError(f"scene.bin が見つかりません: {scene_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    orig_path, meta_path = _backup_paths(backup_dir, lang)
    meta = _load_meta(meta_path)

    if not orig_path.is_file():
        current_bytes = scene_path.read_bytes()
        # Validate before saving backup
        unpack_scene_bin(current_bytes)
        original_sha = sha256_bytes(current_bytes)
        _atomic_write_bytes(orig_path, current_bytes)
        meta["lang"] = lang
        meta["original_sha256"] = original_sha
        meta["backed_up_at"] = datetime.now(timezone.utc).isoformat()
    else:
        original_sha = meta.get("original_sha256")
        source_bytes_check = orig_path.read_bytes()
        actual_orig_sha = sha256_bytes(source_bytes_check)
        if original_sha and actual_orig_sha != original_sha:
            raise ScenePatchError(
                "オリジナルバックアップのSHA-256検証に失敗しました。安全のため処理を中止します。"
            )
        original_sha = actual_orig_sha
        meta["original_sha256"] = original_sha

    source_bytes = orig_path.read_bytes()
    patched_bytes, summary = patch_scene_bytes(source_bytes, config)
    patched_sha = sha256_bytes(patched_bytes)

    _atomic_write_bytes(scene_path, patched_bytes)

    meta["lang"] = lang
    meta["patched_sha256"] = patched_sha
    meta["applied_config"] = config.to_dict()
    meta["summary"] = summary
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_write_json(meta_path, meta)

    return get_patch_status(scene_path, backup_dir, lang)


def restore_vanilla(scene_path: Path, backup_dir: Path, lang: str) -> PatchStatus:
    """Restore scene.bin from the verified original backup."""
    orig_path, meta_path = _backup_paths(backup_dir, lang)
    if not orig_path.is_file():
        raise ScenePatchError(
            f"lang-{lang} のオリジナルバックアップが見つかりません。復元できません。"
        )

    orig_bytes = orig_path.read_bytes()
    orig_sha = sha256_bytes(orig_bytes)
    meta = _load_meta(meta_path)
    expected_sha = meta.get("original_sha256")
    if expected_sha and orig_sha != expected_sha:
        raise ScenePatchError(
            "バックアップファイルのSHA-256がメタデータと一致しません。復元を中止しました。"
        )

    unpack_scene_bin(orig_bytes)
    _atomic_write_bytes(scene_path, orig_bytes)

    meta["lang"] = lang
    meta["original_sha256"] = orig_sha
    meta["patched_sha256"] = None
    meta["applied_config"] = None
    meta["restored_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_write_json(meta_path, meta)

    return get_patch_status(scene_path, backup_dir, lang)
