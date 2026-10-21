"""Real Tk integration using generated CT data and a temporary output directory."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "scripts"))
import segqc_viewer as viewer
from create_demo import create_demo


@unittest.skipIf(sys.platform.startswith("linux") and not os.environ.get("DISPLAY"),
                 "Tk integration requires a desktop DISPLAY")
class TkIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.pixels, self.target = create_demo(self.folder)
        shutil.copytree(self.folder / "影像" / "synthetic_case",
                        self.folder / "影像" / "synthetic_case_2")
        shutil.copyfile(self.folder / "masks" / "synthetic_case.nii.gz",
                        self.folder / "masks" / "synthetic_case_2.nii.gz")
        self.output = self.folder / "output"
        self.output.mkdir()
        (self.output / "设置.json").write_text(json.dumps({"scorer": "Synthetic Tester"}),
                                             encoding="utf-8")
        self.addCleanup(patch.stopall)
        patch.object(viewer, "OUTPUT_DIR", self.output).start()
        patch.object(viewer, "CT_ROOT", self.folder / "影像").start()
        patch.object(viewer, "MASK_DIR", self.folder / "masks").start()
        self.dialogs = []
        for function in ("showerror", "showwarning", "showinfo", "askyesno", "askretrycancel"):
            self.dialogs.append(patch.object(
                viewer.messagebox, function,
                side_effect=AssertionError(f"Unexpected modal dialog: {function}")).start())
        self.dialogs.append(patch.object(viewer.simpledialog, "askstring",
                                        side_effect=AssertionError("Unexpected scorer prompt")).start())
        self.dialogs.append(patch.object(viewer.filedialog, "askdirectory",
                                        side_effect=AssertionError("Unexpected directory prompt")).start())
        viewer._RESULTS_READ_FAILED = None
        self.roots = []
        self.callback_errors = []
        self.addCleanup(self.destroy_roots)

    def destroy_roots(self):
        for root in self.roots:
            try:
                root.destroy()
            except viewer.tk.TclError:
                pass

    def open_app(self):
        try:
            root = viewer.tk.Tk()
        except viewer.tk.TclError as error:
            self.skipTest(f"Tk desktop unavailable: {error}")
        self.roots.append(root)
        root.geometry("1200x800")
        root.report_callback_exception = lambda *error: self.callback_errors.append(error)
        app = viewer.QCApp(root)
        self.run_events(root)
        return root, app

    def run_events(self, root):
        root.after(100, root.quit)
        root.mainloop()
        root.update_idletasks()

    def test_render_grade_note_and_resume(self):
        root, app = self.open_app()
        np.testing.assert_array_equal(app.vol, self.pixels)
        np.testing.assert_array_equal(app.mask, self.target.astype(np.uint8))
        self.assertEqual(app.pids, ["synthetic_case", "synthetic_case_2"])
        self.assertEqual(app.z, int(self.target.sum(axis=(1, 2)).argmax()))

        for mode in ("fill", "outline", "off"):
            with self.subTest(mode=mode):
                app.set_mask_mode(mode)
                start = app.z
                app.step(1)
                root.update()
                self.assertEqual(app.z, start + 1)
                self.assertIsNotNone(app._img_ref)
                self.assertEqual(len(app.canvas.find_all()), 1)
                self.assertEqual(app.canvas.type(app.canvas.find_all()[0]), "image")

        app.ent_note.insert(0, "合成备注,初评")
        app.grade("minor")
        self.assertEqual(viewer.load_results()["synthetic_case"]["grade"], "minor")
        app.ent_note.delete(0, "end")
        app.ent_note.insert(0, "修改备注,切换时保存")
        app.goto(1)
        root.update()
        self.assertEqual(viewer.load_results()["synthetic_case"]["note"], "修改备注,切换时保存")
        np.testing.assert_array_equal(app.vol, self.pixels)
        np.testing.assert_array_equal(app.mask, self.target.astype(np.uint8))
        app.grade("pass")
        app.ent_note.insert(0, "关闭时保存")
        app.wl, app.ww = 35.0, 350.0
        app.set_mask_mode("outline")
        self.run_events(root)
        app.on_close()

        settings = viewer.load_config()
        self.assertEqual(settings["last_pid"], "synthetic_case_2")
        self.assertEqual((settings["wl"], settings["ww"]), (35.0, 350.0))
        self.assertEqual(viewer.load_results()["synthetic_case_2"]["note"], "关闭时保存")
        second_root, restored = self.open_app()
        self.assertEqual(restored._cur_pid, "synthetic_case_2")
        self.assertEqual(restored.cur, 1)
        self.assertEqual(restored.scorer, "Synthetic Tester")
        self.assertEqual(restored.mask_mode, "outline")
        self.assertEqual((restored.wl, restored.ww), (35.0, 350.0))
        self.assertEqual(restored.results["synthetic_case"]["grade"], "minor")
        self.assertEqual(restored.results["synthetic_case_2"]["grade"], "pass")
        self.assertEqual(restored.ent_note.get(), "关闭时保存")
        np.testing.assert_array_equal(restored.vol, self.pixels)
        np.testing.assert_array_equal(restored.mask, self.target.astype(np.uint8))
        self.run_events(second_root)
        restored.on_close()
        self.assertEqual(self.callback_errors, [])
        for dialog in self.dialogs:
            dialog.assert_not_called()


if __name__ == "__main__":
    unittest.main()
