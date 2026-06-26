# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from inkcalc import collect_ghostscript_bitonal_plates, generate_ghostscript_bitonal_plates, run_ghostscript_tiff_device, run_tiffsep1, terminate_active_ghostscript_processes


class FakeGhostscriptProcess:
    next_pid = 1000

    def __init__(self, cmd: list[str], *, stdout_text: str = "", stderr_text: str = "", returncode: int = 0) -> None:
        self.cmd = cmd
        self.stdout_text = stdout_text
        self.stderr_text = stderr_text
        self.returncode = returncode
        self.pid = FakeGhostscriptProcess.next_pid
        FakeGhostscriptProcess.next_pid += 1
        self.terminated = False
        self.killed = False

    def communicate(self, timeout: int | None = None) -> tuple[str, str]:
        return self.stdout_text, self.stderr_text

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: int | None = None) -> int:
        if self.returncode is None:
            self.returncode = -15
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class HangingGhostscriptProcess(FakeGhostscriptProcess):
    def __init__(self, cmd: list[str]) -> None:
        super().__init__(cmd, returncode=None)

    def communicate(self, timeout: int | None = None) -> tuple[str, str]:
        raise subprocess.TimeoutExpired(self.cmd, timeout)

    def poll(self) -> int | None:
        return self.returncode


class InkcalcGhostscriptBitonalTests(unittest.TestCase):
    def test_run_tiffsep1_uses_ghostscript_bitonal_device(self) -> None:
        temp_root = (Path(__file__).resolve().parent / ".test_tmp")
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root, ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            source = root / "job.pdf"
            source.write_bytes(b"%PDF-1.4\n")
            output_dir = root / "out"

            def fake_popen(cmd: list[str], **_kwargs: object) -> FakeGhostscriptProcess:
                self.assertIn("-sDEVICE=tiffsep1", cmd)
                Image.fromarray(np.zeros((8, 8), dtype=np.uint8)).save(output_dir / "sep_001(Cyan).tif")
                return FakeGhostscriptProcess(cmd)

            with patch("inkcalc.subprocess.Popen", side_effect=fake_popen):
                tiffs = run_tiffsep1("gs", source, output_dir, 2400)

            self.assertEqual([path.name for path in tiffs], ["sep_001(Cyan).tif"])

    def test_collect_named_tiffsep1_plates(self) -> None:
        temp_root = (Path(__file__).resolve().parent / ".test_tmp")
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root, ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            source = root / "job.pdf"
            source.write_bytes(b"%PDF-1.4\n")
            cyan = root / "sep_001(Cyan).tif"
            empty = root / "sep_002(Magenta).tif"
            Image.fromarray(np.zeros((8, 8), dtype=np.uint8)).save(cyan)
            Image.fromarray(np.full((8, 8), 255, dtype=np.uint8)).save(empty)

            plates = collect_ghostscript_bitonal_plates(source, [cyan, empty])

            self.assertEqual(plates, {"C": cyan})

    def test_collect_separated_ps_composite_pages_from_plate_color(self) -> None:
        temp_root = (Path(__file__).resolve().parent / ".test_tmp")
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root, ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            source = root / "separated.ps"
            source.write_text("%%PlateColor: Magenta\n", encoding="latin-1")
            page = root / "sep_001.tif"
            Image.fromarray(np.zeros((8, 8), dtype=np.uint8)).save(page)

            plates = collect_ghostscript_bitonal_plates(source, [page])

            self.assertEqual(plates, {"M": page})

    def test_generate_ghostscript_bitonal_is_optional(self) -> None:
        temp_root = (Path(__file__).resolve().parent / ".test_tmp")
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root, ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            source = root / "job.pdf"
            source.write_bytes(b"%PDF-1.4\n")

            with patch("inkcalc.run_tiffsep1", side_effect=RuntimeError("unsupported")):
                plates = generate_ghostscript_bitonal_plates("gs", [source], root / "out", 2400)

            self.assertEqual(plates, {})

    def test_high_dpi_skips_optional_tiffsep1_pass(self) -> None:
        temp_root = (Path(__file__).resolve().parent / ".test_tmp")
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root, ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            source = root / "job.pdf"
            source.write_bytes(b"%PDF-1.4\n")
            progress: list[str] = []

            with patch("inkcalc.run_tiffsep1") as mocked:
                plates = generate_ghostscript_bitonal_plates("gs", [source], root / "out", 2540, progress.append)

            mocked.assert_not_called()
            self.assertEqual(plates, {})
            self.assertTrue(any("пропущены" in item for item in progress))

    def test_ghostscript_timeout_reports_actionable_error(self) -> None:
        temp_root = (Path(__file__).resolve().parent / ".test_tmp")
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root, ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            source = root / "job.pdf"
            source.write_bytes(b"%PDF-1.4\n")

            with patch("inkcalc.subprocess.Popen", side_effect=lambda cmd, **_kwargs: HangingGhostscriptProcess(cmd)):
                with self.assertRaisesRegex(RuntimeError, "не ответил"):
                    run_ghostscript_tiff_device("gs", source, root / "out", 2540, device="tiffsep", timeout_seconds=1)

    def test_active_ghostscript_process_can_be_terminated_on_close(self) -> None:
        process = HangingGhostscriptProcess(["gs"])

        with patch("inkcalc.subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(RuntimeError, "не ответил"):
                run_ghostscript_tiff_device("gs", Path("job.pdf"), (Path(__file__).resolve().parent / ".test_tmp"), 600, device="tiffsep", timeout_seconds=1)

        self.assertTrue(process.terminated or process.killed)
        terminate_active_ghostscript_processes()


if __name__ == "__main__":
    unittest.main()
