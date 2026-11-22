"""Unit and integration tests for FF7 scene.bin drop rate patcher."""

from __future__ import annotations

import random
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core.scene_patcher import (  # noqa: E402
    AP_SENTINEL,
    BLOCK_SIZE,
    DROP_RATE_100,
    ENEMY_AP_OFFSET,
    ENEMY_DATA_OFFSET,
    ENEMY_EXP_OFFSET,
    ENEMY_GIL_OFFSET,
    ENEMY_ITEM_IDS_OFFSET,
    ENEMY_ITEM_RATES_OFFSET,
    ENEMY_RECORD_SIZE,
    EXP_SENTINEL,
    GIL_SENTINEL,
    KERNEL_INIT_SECTION_INDEX,
    KERNEL_SCENE_LOOKUP_OFFSET,
    KERNEL_SCENE_LOOKUP_SIZE,
    MAX_SAFE_AP,
    MAX_SAFE_EXP,
    MAX_SAFE_GIL,
    SCENE_RAW_SIZE,
    STEAL_RATE_100,
    BlockOverflowError,
    DropPatchConfig,
    ScenePatchError,
    apply_drop_patch,
    get_patch_status,
    inspect_scene_bytes,
    pack_scene_bin,
    patch_scene_bytes,
    restore_vanilla,
    sha256_bytes,
    unpack_scene_bin,
)

GAME_DATA_DIR = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\FINAL FANTASY VII Steam Edition"
    r"\ff7\workingdir\data"
)
REAL_JA_SCENE_BIN = GAME_DATA_DIR / "lang-ja" / "battle" / "scene.bin"
REAL_EN_SCENE_BIN = GAME_DATA_DIR / "lang-en" / "battle" / "scene.bin"
REAL_EN_KERNEL_BIN = GAME_DATA_DIR / "lang-en" / "kernel" / "kernel.bin"


def _make_scene(
    enemy_ids: tuple[int, int, int],
    enemy_slots: dict[int, list[tuple[int, int]]],
    enemy_rewards: dict[int, tuple[int, int, int]] | None = None,
) -> bytes:
    """Create a valid 7808-byte scene buffer with specified enemy item slots and (exp, ap, gil)."""
    buf = bytearray(SCENE_RAW_SIZE)
    struct.pack_into("<3H", buf, 0, *enemy_ids)
    for eidx in range(3):
        if enemy_ids[eidx] == 0xFFFF:
            continue
        base = ENEMY_DATA_OFFSET + eidx * ENEMY_RECORD_SIZE
        slots = list(enemy_slots.get(eidx, []))
        while len(slots) < 4:
            slots.append((0xFF, 0xFFFF))
        rates = [r for r, _ in slots[:4]]
        items = [it for _, it in slots[:4]]
        buf[base + ENEMY_ITEM_RATES_OFFSET : base + ENEMY_ITEM_RATES_OFFSET + 4] = bytes(rates)
        struct.pack_into("<4H", buf, base + ENEMY_ITEM_IDS_OFFSET, *items)
        if enemy_rewards and eidx in enemy_rewards:
            exp, ap, gil = enemy_rewards[eidx]
            struct.pack_into("<H", buf, base + ENEMY_AP_OFFSET, ap)
            struct.pack_into("<II", buf, base + ENEMY_EXP_OFFSET, exp, gil)
    return bytes(buf)


def _extract_enemy_rewards(raw: bytes, eidx: int) -> tuple[int, int, int]:
    base = ENEMY_DATA_OFFSET + eidx * ENEMY_RECORD_SIZE
    ap = struct.unpack_from("<H", raw, base + ENEMY_AP_OFFSET)[0]
    exp, gil = struct.unpack_from("<II", raw, base + ENEMY_EXP_OFFSET)
    return exp, ap, gil


def _extract_enemy_slots(raw: bytes, eidx: int) -> list[tuple[int, int]]:
    base = ENEMY_DATA_OFFSET + eidx * ENEMY_RECORD_SIZE
    rates = raw[base + ENEMY_ITEM_RATES_OFFSET : base + ENEMY_ITEM_RATES_OFFSET + 4]
    items = struct.unpack_from("<4H", raw, base + ENEMY_ITEM_IDS_OFFSET)
    return list(zip(rates, items))


class TestScenePatcherSynthetic(unittest.TestCase):
    """Tests using synthetic multi-block scene.bin data."""

    def setUp(self) -> None:
        self.scene0 = _make_scene(
            (10, 20, 0xFFFF),
            {
                # Enemy 0: common drop (8, item 100), rarer drop (2, item 200), steal (0x88, item 300)
                0: [(8, 100), (2, 200), (0x88, 300), (0xFF, 0xFFFF)],
                # Enemy 1: tie drops (8, item 11) and (8, item 12), already-63 drop (63, item 13)
                1: [(8, 11), (8, 12), (63, 13), (0xA0, 400)],
            },
        )
        self.scene1 = _make_scene(
            (30, 0xFFFF, 0xFFFF),
            {
                0: [(32, 50), (0xFF, 0xFFFF), (0xFF, 0xFFFF), (0xFF, 0xFFFF)],
            },
        )
        self.scene2 = _make_scene(
            (40, 50, 60),
            {
                0: [(8, 1), (2, 2), (2, 3), (0x90, 99)],
                1: [(0x88, 55), (0xFF, 0xFFFF), (0xFF, 0xFFFF), (0xFF, 0xFFFF)],
                2: [(63, 77), (0xFF, 0xFFFF), (0xFF, 0xFFFF), (0xFF, 0xFFFF)],
            },
        )
        self.vanilla_bytes = pack_scene_bin([[self.scene0, self.scene1], [self.scene2]])

    def test_unpack_pack_roundtrip(self) -> None:
        blocks = unpack_scene_bin(self.vanilla_bytes)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(len(blocks[0]), 2)
        self.assertEqual(len(blocks[1]), 1)
        self.assertEqual(blocks[0][0], self.scene0)
        self.assertEqual(blocks[0][1], self.scene1)
        self.assertEqual(blocks[1][0], self.scene2)

    def test_rare_first_keeps_steals_untouched_when_disabled(self) -> None:
        patched, summary = patch_scene_bytes(
            self.vanilla_bytes,
            DropPatchConfig(drop_100=True, rare_first=True, steal_100=False),
        )
        self.assertEqual(summary["scenes_count"], 3)
        self.assertGreater(summary["enemies_reordered"], 0)

        blocks = unpack_scene_bin(patched)
        # Enemy 0: item 200 (was rate 2) moves before item 100 (was rate 8); steal stays 0x88
        self.assertEqual(
            _extract_enemy_slots(blocks[0][0], 0),
            [(DROP_RATE_100, 200), (DROP_RATE_100, 100), (0x88, 300), (0xFF, 0xFFFF)],
        )
        # Enemy 1: ties (rate 8) keep relative order 11 -> 12 -> 13; steal stays 0xA0
        self.assertEqual(
            _extract_enemy_slots(blocks[0][0], 1),
            [(DROP_RATE_100, 11), (DROP_RATE_100, 12), (DROP_RATE_100, 13), (0xA0, 400)],
        )
        # Block 1 scene 0 enemy 0: both rate-2 items (2, 3) precede rate-8 item (1) in stable order
        self.assertEqual(
            _extract_enemy_slots(blocks[1][0], 0),
            [(DROP_RATE_100, 2), (DROP_RATE_100, 3), (DROP_RATE_100, 1), (0x90, 99)],
        )

    def test_normal_order_and_steal_100(self) -> None:
        patched, _ = patch_scene_bytes(
            self.vanilla_bytes,
            DropPatchConfig(drop_100=True, rare_first=False, steal_100=True),
        )
        blocks = unpack_scene_bin(patched)
        # Original order preserved: item 100 stays slot 0, item 200 slot 1, steal becomes 0xBF
        self.assertEqual(
            _extract_enemy_slots(blocks[0][0], 0),
            [(DROP_RATE_100, 100), (DROP_RATE_100, 200), (STEAL_RATE_100, 300), (0xFF, 0xFFFF)],
        )
        stats = inspect_scene_bytes(patched)
        self.assertEqual(stats.non_max_drop_slot_count, 0)
        self.assertEqual(stats.non_max_steal_slot_count, 0)

    def test_apply_switch_modes_and_restore_vanilla(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            scene_path = tmp_path / "scene.bin"
            backup_dir = tmp_path / "backups"
            scene_path.write_bytes(self.vanilla_bytes)
            orig_sha = sha256_bytes(self.vanilla_bytes)

            st0 = get_patch_status(scene_path, backup_dir, "ja")
            self.assertEqual(st0.state, "VANILLA")
            self.assertFalse(st0.has_backup)

            # 1. Apply normal-order first (would lose original rate ordering if not backed up!)
            st1 = apply_drop_patch(
                scene_path,
                backup_dir,
                "ja",
                DropPatchConfig(drop_100=True, rare_first=False, steal_100=False),
            )
            self.assertEqual(st1.state, "PATCHED")
            self.assertTrue(st1.has_backup)
            self.assertEqual(st1.backup_sha256, orig_sha)

            # 2. Switch to rare_first=True + steal_100=True; must patch from original backup
            st2 = apply_drop_patch(
                scene_path,
                backup_dir,
                "ja",
                DropPatchConfig(drop_100=True, rare_first=True, steal_100=True),
            )
            self.assertEqual(st2.state, "PATCHED")
            self.assertTrue(st2.applied_config.rare_first)
            self.assertTrue(st2.applied_config.steal_100)
            blocks = unpack_scene_bin(scene_path.read_bytes())
            self.assertEqual(
                _extract_enemy_slots(blocks[0][0], 0),
                [(DROP_RATE_100, 200), (DROP_RATE_100, 100), (STEAL_RATE_100, 300), (0xFF, 0xFFFF)],
            )

            # 3. Restore vanilla and verify exact byte identity
            st3 = restore_vanilla(scene_path, backup_dir, "ja")
            self.assertEqual(st3.state, "VANILLA")
            self.assertEqual(sha256_bytes(scene_path.read_bytes()), orig_sha)

    def test_error_handling_and_overflow_safety(self) -> None:
        with self.assertRaises(ScenePatchError):
            unpack_scene_bin(b"invalid")

        # Build incompressible pseudo-random scenes exceeding 8192 bytes in a single block
        incompressible_scenes = [
            random.Random(s_idx).randbytes(SCENE_RAW_SIZE) for s_idx in range(16)
        ]
        with self.assertRaises(BlockOverflowError):
            pack_scene_bin([incompressible_scenes])

        # Verify tampered backup metadata aborts restore without modifying scene.bin
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            scene_path = tmp_path / "scene.bin"
            backup_dir = tmp_path / "backups"
            scene_path.write_bytes(self.vanilla_bytes)
            apply_drop_patch(scene_path, backup_dir, "ja", DropPatchConfig())
            patched_sha = sha256_bytes(scene_path.read_bytes())

            orig_backup = backup_dir / "lang-ja_scene.bin.orig"
            orig_backup.write_bytes(b"tampered")
            with self.assertRaises(ScenePatchError):
                restore_vanilla(scene_path, backup_dir, "ja")
            self.assertEqual(sha256_bytes(scene_path.read_bytes()), patched_sha)

    def test_reward_multipliers_scaling_clamping_and_sentinels(self) -> None:
        scene_rewards = _make_scene(
            (10, 20, 30),
            {
                0: [(8, 100), (0xFF, 0xFFFF), (0xFF, 0xFFFF), (0xFF, 0xFFFF)],
                1: [(8, 101), (0xFF, 0xFFFF), (0xFF, 0xFFFF), (0xFF, 0xFFFF)],
                2: [(8, 102), (0xFF, 0xFFFF), (0xFF, 0xFFFF), (0xFF, 0xFFFF)],
            },
            {
                0: (100, 10, 201),       # normal
                1: (0, 0, 0),            # zero rewards
                2: (100000, 50000, 100000),  # high rewards
            },
        )
        scene_sentinel = _make_scene(
            (40, 0xFFFF, 0xFFFF),
            {0: [(8, 103), (0xFF, 0xFFFF), (0xFF, 0xFFFF), (0xFF, 0xFFFF)]},
            {0: (EXP_SENTINEL, AP_SENTINEL, GIL_SENTINEL)},
        )
        raw_bin = pack_scene_bin([[scene_rewards, scene_sentinel]])

        # Scale with drop_100=False -> drops unchanged, rewards scaled & clamped
        patched, summary = patch_scene_bytes(
            raw_bin,
            DropPatchConfig(
                drop_100=False,
                rare_first=False,
                steal_100=False,
                exp_multiplier=2.5,
                ap_multiplier=3.0,
                gil_multiplier=0.5,
            ),
        )
        self.assertGreater(summary["exp_updated"], 0)
        blocks = unpack_scene_bin(patched)
        # Drop rate must stay 8 because drop_100=False
        self.assertEqual(_extract_enemy_slots(blocks[0][0], 0)[0], (8, 100))
        self.assertEqual(_extract_enemy_rewards(blocks[0][0], 0), (250, 30, 100))
        self.assertEqual(_extract_enemy_rewards(blocks[0][0], 1), (0, 0, 0))
        self.assertEqual(_extract_enemy_rewards(blocks[0][0], 2), (250000, MAX_SAFE_AP, 50000))
        # Sentinels must be preserved untouched
        self.assertEqual(
            _extract_enemy_rewards(blocks[0][1], 0),
            (EXP_SENTINEL, AP_SENTINEL, GIL_SENTINEL),
        )

        # Zero multiplier -> normal enemies become 0, sentinels stay untouched
        zeroed, _ = patch_scene_bytes(
            raw_bin,
            DropPatchConfig(
                drop_100=False,
                exp_multiplier=0.0,
                ap_multiplier=0.0,
                gil_multiplier=0.0,
            ),
        )
        z_blocks = unpack_scene_bin(zeroed)
        self.assertEqual(_extract_enemy_rewards(z_blocks[0][0], 0), (0, 0, 0))
        self.assertEqual(
            _extract_enemy_rewards(z_blocks[0][1], 0),
            (EXP_SENTINEL, AP_SENTINEL, GIL_SENTINEL),
        )

        # 100x clamps EXP & Gil to 9,999,999
        maxed, _ = patch_scene_bytes(
            raw_bin,
            DropPatchConfig(
                drop_100=False,
                exp_multiplier=100.0,
                ap_multiplier=100.0,
                gil_multiplier=100.0,
            ),
        )
        m_blocks = unpack_scene_bin(maxed)
        self.assertEqual(
            _extract_enemy_rewards(m_blocks[0][0], 2),
            (MAX_SAFE_EXP, MAX_SAFE_AP, MAX_SAFE_GIL),
        )

        # Invalid multipliers must raise ScenePatchError
        for bad_val in (-1.0, 101.0, float("nan"), float("inf")):
            with self.assertRaises(ScenePatchError):
                DropPatchConfig(exp_multiplier=bad_val).validate()

    def test_multiplier_reapply_uses_original_backup_without_drift(self) -> None:
        scene = _make_scene(
            (10, 0xFFFF, 0xFFFF),
            {0: [(8, 100), (0xFF, 0xFFFF), (0xFF, 0xFFFF), (0xFF, 0xFFFF)]},
            {0: (100, 10, 50)},
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            scene_path = tmp_path / "scene.bin"
            backup_dir = tmp_path / "backups"
            scene_path.write_bytes(pack_scene_bin([[scene]]))

            apply_drop_patch(
                scene_path,
                backup_dir,
                "ja",
                DropPatchConfig(drop_100=False, exp_multiplier=3.0, ap_multiplier=3.0, gil_multiplier=3.0),
            )
            blocks_3x = unpack_scene_bin(scene_path.read_bytes())
            self.assertEqual(_extract_enemy_rewards(blocks_3x[0][0], 0), (300, 30, 150))

            # Reapplying 2x must produce 200/20/100 (NOT 600/60/300!)
            apply_drop_patch(
                scene_path,
                backup_dir,
                "ja",
                DropPatchConfig(drop_100=False, exp_multiplier=2.0, ap_multiplier=2.0, gil_multiplier=2.0),
            )
            blocks_2x = unpack_scene_bin(scene_path.read_bytes())
            self.assertEqual(_extract_enemy_rewards(blocks_2x[0][0], 0), (200, 20, 100))


@unittest.skipUnless(
    REAL_JA_SCENE_BIN.is_file(),
    "Real game scene.bin not found in Steam directory",
)
class TestScenePatcherRealCopy(unittest.TestCase):
    """Integration test on a TEMPORARY COPY of real FF7 Steam Edition scene.bin / kernel.bin."""

    def test_real_scene_bin_all_modes_on_temp_copy(self) -> None:
        # Pick any unpatched language file if lang-ja is currently user-patched
        vanilla_source = next(
            (
                p
                for p in (
                    REAL_JA_SCENE_BIN,
                    REAL_EN_SCENE_BIN,
                    GAME_DATA_DIR / "lang-fr" / "battle" / "scene.bin",
                )
                if p.is_file() and inspect_scene_bytes(p.read_bytes()).non_max_drop_slot_count > 0
            ),
            REAL_JA_SCENE_BIN,
        )
        lang_code = vanilla_source.parent.parent.name.replace("lang-", "")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            copy_path = tmp_path / "scene.bin"
            backup_dir = tmp_path / "backups"
            shutil.copy2(vanilla_source, copy_path)

            orig_bytes = copy_path.read_bytes()
            orig_sha = sha256_bytes(orig_bytes)
            orig_stats = inspect_scene_bytes(orig_bytes)
            self.assertEqual(orig_stats.scene_count, 256)
            self.assertGreater(orig_stats.drop_slot_count, 0)
            if vanilla_source != REAL_JA_SCENE_BIN or orig_stats.non_max_drop_slot_count > 0:
                self.assertGreater(orig_stats.non_max_drop_slot_count, 0)

            configs = [
                DropPatchConfig(drop_100=True, rare_first=True, steal_100=False),
                DropPatchConfig(drop_100=True, rare_first=True, steal_100=True),
                DropPatchConfig(drop_100=True, rare_first=False, steal_100=False),
                DropPatchConfig(drop_100=True, rare_first=False, steal_100=True),
            ]
            for cfg in configs:
                status = apply_drop_patch(copy_path, backup_dir, lang_code, cfg)
                self.assertEqual(status.state, "PATCHED")
                self.assertIsNotNone(status.stats)
                self.assertEqual(status.stats.block_count, orig_stats.block_count)
                self.assertEqual(status.stats.scene_count, orig_stats.scene_count)
                self.assertEqual(status.stats.non_max_drop_slot_count, 0)
                if cfg.steal_100:
                    self.assertEqual(status.stats.non_max_steal_slot_count, 0)
                else:
                    self.assertEqual(
                        status.stats.non_max_steal_slot_count,
                        orig_stats.non_max_steal_slot_count,
                    )

            restored_status = restore_vanilla(copy_path, backup_dir, lang_code)
            self.assertEqual(restored_status.state, "VANILLA")
            self.assertEqual(sha256_bytes(copy_path.read_bytes()), orig_sha)

    def test_real_scene_bin_multipliers_ja_and_en_kernel_sync_on_temp_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            backup_dir = tmp_path / "backups"

            # 1. lang-ja copy: fits without kernel sync
            ja_scene = tmp_path / "lang-ja" / "battle" / "scene.bin"
            ja_scene.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REAL_JA_SCENE_BIN, ja_scene)
            ja_orig_sha = sha256_bytes(ja_scene.read_bytes())

            ja_status = apply_drop_patch(
                ja_scene,
                backup_dir,
                "ja",
                DropPatchConfig(
                    drop_100=True,
                    rare_first=True,
                    steal_100=True,
                    exp_multiplier=5.0,
                    ap_multiplier=10.0,
                    gil_multiplier=3.5,
                ),
            )
            self.assertEqual(ja_status.state, "PATCHED")
            self.assertFalse(ja_status.kernel_modified)
            self.assertEqual(ja_status.stats.scene_count, 256)
            self.assertEqual(ja_status.stats.max_ap, MAX_SAFE_AP)

            ja_restored = restore_vanilla(ja_scene, backup_dir, "ja")
            self.assertEqual(ja_restored.state, "VANILLA")
            self.assertEqual(sha256_bytes(ja_scene.read_bytes()), ja_orig_sha)

            # 2. lang-en copy: high multiplier overflows block 13 -> repacks & syncs kernel.bin
            if REAL_EN_SCENE_BIN.is_file() and REAL_EN_KERNEL_BIN.is_file():
                en_scene = tmp_path / "lang-en" / "battle" / "scene.bin"
                en_kernel = tmp_path / "lang-en" / "kernel" / "kernel.bin"
                en_scene.parent.mkdir(parents=True, exist_ok=True)
                en_kernel.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(REAL_EN_SCENE_BIN, en_scene)
                shutil.copy2(REAL_EN_KERNEL_BIN, en_kernel)

                en_scene_orig_sha = sha256_bytes(en_scene.read_bytes())
                en_kernel_orig_sha = sha256_bytes(en_kernel.read_bytes())

                en_status = apply_drop_patch(
                    en_scene,
                    backup_dir,
                    "en",
                    DropPatchConfig(
                        drop_100=True,
                        rare_first=True,
                        steal_100=True,
                        exp_multiplier=10.0,
                        ap_multiplier=10.0,
                        gil_multiplier=10.0,
                    ),
                    kernel_path=en_kernel,
                )
                self.assertEqual(en_status.state, "PATCHED")
                self.assertTrue(en_status.kernel_modified)
                self.assertEqual(en_status.stats.scene_count, 256)

                # Verify kernel.bin section 2 lookup table matches repacked scene.bin blocks
                repacked_blocks = unpack_scene_bin(en_scene.read_bytes())
                expected_starts = []
                cur = 0
                for b in repacked_blocks:
                    expected_starts.append(cur)
                    cur += len(b)
                expected_table = bytes(expected_starts) + b"\xff" * (
                    KERNEL_SCENE_LOOKUP_SIZE - len(expected_starts)
                )

                k_bytes = en_kernel.read_bytes()
                off = 0
                sec2_raw = b""
                for idx in range(KERNEL_INIT_SECTION_INDEX + 1):
                    clen, _ulen, _sid = struct.unpack_from("<HHH", k_bytes, off)
                    comp = k_bytes[off + 6 : off + 6 + clen]
                    if idx == KERNEL_INIT_SECTION_INDEX:
                        sec2_raw = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(comp)
                    off += 6 + clen
                self.assertEqual(
                    sec2_raw[
                        KERNEL_SCENE_LOOKUP_OFFSET : KERNEL_SCENE_LOOKUP_OFFSET
                        + KERNEL_SCENE_LOOKUP_SIZE
                    ],
                    expected_table,
                )

                # Restoring vanilla must return BOTH scene.bin and kernel.bin to exact original SHA-256
                en_restored = restore_vanilla(en_scene, backup_dir, "en", kernel_path=en_kernel)
                self.assertEqual(en_restored.state, "VANILLA")
                self.assertFalse(en_restored.kernel_modified)
                self.assertEqual(sha256_bytes(en_scene.read_bytes()), en_scene_orig_sha)
                self.assertEqual(sha256_bytes(en_kernel.read_bytes()), en_kernel_orig_sha)


if __name__ == "__main__":
    unittest.main()
