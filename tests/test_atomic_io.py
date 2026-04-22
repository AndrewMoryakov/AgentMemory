import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentmemory.runtime.atomic_io import atomic_write_json, atomic_write_text


class AtomicWriteTextTests(unittest.TestCase):
    def test_creates_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "deep" / "file.txt"
            atomic_write_text(target, "hello")
            self.assertTrue(target.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), "hello")

    def test_overwrites_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "f.txt"
            target.write_text("old", encoding="utf-8")
            atomic_write_text(target, "new")
            self.assertEqual(target.read_text(encoding="utf-8"), "new")

    def test_crash_mid_write_preserves_previous_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "f.txt"
            target.write_text("original", encoding="utf-8")

            # Simulate a crash between tempfile close and os.replace.
            with mock.patch("agentmemory.runtime.atomic_io.os.replace", side_effect=OSError("simulated")):
                with self.assertRaises(OSError):
                    atomic_write_text(target, "corrupted")

            self.assertEqual(target.read_text(encoding="utf-8"), "original")

    def test_crash_mid_write_leaves_no_temp_file_behind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "f.txt"
            target.write_text("x", encoding="utf-8")

            with mock.patch("agentmemory.runtime.atomic_io.os.replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    atomic_write_text(target, "y")

            leftover = [p.name for p in Path(tmp).iterdir() if p.name != "f.txt"]
            self.assertEqual(leftover, [], f"temp files left behind: {leftover}")

    def test_target_is_replaced_atomically_not_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "f.txt"
            target.write_text("ABCDE", encoding="utf-8")
            inode_before = target.stat().st_ino if hasattr(target.stat(), "st_ino") else None

            atomic_write_text(target, "Z")

            self.assertEqual(target.read_text(encoding="utf-8"), "Z")
            if inode_before is not None and os.name != "nt":
                # On POSIX, os.replace onto an existing file gives a new inode
                # (the temp file's), confirming the replace path ran.
                self.assertNotEqual(target.stat().st_ino, inode_before)

    def test_respects_explicit_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "f.txt"
            atomic_write_text(target, "ascii-only", encoding="ascii")
            self.assertEqual(target.read_text(encoding="ascii"), "ascii-only")


class AtomicWriteJsonTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "data.json"
            payload = {"a": 1, "b": [1, 2, 3], "c": {"nested": True}}
            atomic_write_json(target, payload)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), payload)

    def test_writes_trailing_newline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "data.json"
            atomic_write_json(target, {"x": 1})
            self.assertTrue(target.read_text(encoding="utf-8").endswith("\n"))

    def test_ensure_ascii_default_escapes_non_ascii(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "data.json"
            atomic_write_json(target, {"k": "привет"})
            raw = target.read_text(encoding="utf-8")
            self.assertNotIn("привет", raw)
            self.assertIn("\\u", raw)

    def test_crash_preserves_prior_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "data.json"
            atomic_write_json(target, {"v": 1})

            with mock.patch("agentmemory.runtime.atomic_io.os.replace", side_effect=OSError):
                with self.assertRaises(OSError):
                    atomic_write_json(target, {"v": 2})

            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"v": 1})


if __name__ == "__main__":
    unittest.main()
