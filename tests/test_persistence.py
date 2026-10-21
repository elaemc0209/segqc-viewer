"""Persistence regressions using synthetic records only; no Tk window or real cases."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import segqc_viewer as viewer


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.path = self.folder / "质控结果.csv"
        self.addCleanup(patch.stopall)
        patch.object(viewer, "data_dir", return_value=self.folder).start()
        self.warning = patch.object(viewer.messagebox, "showerror").start()
        viewer._RESULTS_READ_FAILED = None
        self.records = {"synthetic": dict(patient_id="synthetic", grade="pass",
                                          note='逗号,换行\n与"引号"', scorer="Tester", time="")}

    def test_unicode_csv_roundtrip(self):
        self.assertTrue(viewer.save_results(self.records))
        self.assertEqual(viewer.load_results(), self.records)

    def test_replace_failure_keeps_old_file_and_warns_on_each_retry(self):
        self.assertTrue(viewer.save_results(self.records))
        original = self.path.read_bytes()
        self.records["synthetic"]["grade"] = "fail"
        with patch.object(viewer.os, "replace", side_effect=PermissionError("locked")):
            self.assertFalse(viewer.save_results(self.records))
            self.assertFalse(viewer.save_results(self.records))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.warning.call_count, 2)
        self.assertTrue(viewer.save_results(self.records))
        self.assertEqual(viewer.load_results(), self.records)

    def test_invalid_existing_csv_is_never_overwritten(self):
        invalid_files = [b"not,a,results,header\n",
                         b"patient_id,grade,note,scorer,time\nfirst,pass,,,\nsecond,pass\n",
                         b"patient_id,grade,note,scorer,time\nfirst,pass,,,\nfirst,fail,,,\n",
                         b"\xff\xfe\xfa"]
        for original in invalid_files:
            with self.subTest(original=original):
                self.path.write_bytes(original)
                with self.assertRaisesRegex(ValueError, "禁止覆盖"):
                    viewer.load_results()
                self.assertFalse(viewer.save_results(self.records))
                self.assertEqual(self.path.read_bytes(), original)

    def fake_app(self):
        app = viewer.QCApp.__new__(viewer.QCApp)
        app.root = Mock()
        app.root.tk.call.return_value = ()
        app.results = {}
        app._cur_pid = "synthetic"
        app._busy = False
        app.vol = object()
        app.scorer = "Tester"
        app.ent_note = Mock()
        app.ent_note.get.return_value = "note"
        app._status = Mock()
        app._upsert_row = Mock()
        app._update_stat = Mock()
        app._highlight_grade = Mock()
        app._save_progress = Mock()
        app._load_case = Mock()
        app.pids = ["synthetic", "next"]
        app.cur = 0
        return app

    def test_failed_grade_blocks_navigation_and_close_until_retry_succeeds(self):
        app = self.fake_app()
        with patch.object(viewer, "save_results", return_value=False):
            app.grade("pass")
            self.assertTrue(app._results_dirty)
            app._upsert_row.assert_not_called()
            app.goto(1)
            app._load_case.assert_not_called()
            app._on_space()
            app._load_case.assert_not_called()
            app.on_close()
            app.root.destroy.assert_not_called()
        with patch.object(viewer, "save_results", return_value=True):
            app.goto(1)
        self.assertFalse(app._results_dirty)
        app._load_case.assert_called_once_with(1)
        app.on_close()
        app.root.destroy.assert_called_once()

    def test_failed_note_save_remains_dirty_for_next_retry(self):
        app = self.fake_app()
        app.results = self.records
        with patch.object(viewer, "save_results", return_value=False):
            self.assertFalse(app._save_note())
            self.assertTrue(app._results_dirty)
            self.assertFalse(app._save_note())
        with patch.object(viewer, "save_results", return_value=True) as save:
            self.assertTrue(app._save_note())
            save.assert_called_once_with(app.results)
        self.assertFalse(app._results_dirty)


if __name__ == "__main__":
    unittest.main()
