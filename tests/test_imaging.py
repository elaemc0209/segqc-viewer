import gzip
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pydicom

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import segqc_viewer as viewer
from create_demo import create_demo


class ImagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pixels, self.target = create_demo(self.root)
        self.mask_path = self.root / "masks/synthetic_case.nii.gz"
        self.series = self.root / "影像/synthetic_case"

    def test_exact_synthetic_hu_and_mask(self):
        mask, spacing, meta = viewer.read_nifti_gz(self.mask_path)
        volume, actual_spacing = viewer.load_dicom_series(
            self.series, expect_n=24, mask_geometry=meta)
        np.testing.assert_array_equal(volume, self.pixels)
        np.testing.assert_array_equal(mask, self.target)
        self.assertEqual(actual_spacing, (1, 1, 2))
        self.assertEqual(viewer.resolve_ct_root(self.root), self.root / "影像")

    def test_same_shape_shift_and_mirror_are_rejected(self):
        _, _, meta = viewer.read_nifti_gz(self.mask_path)
        for kind in ("shift", "mirror"):
            broken = dict(meta, affine_lps=meta["affine_lps"].copy())
            if kind == "shift":
                broken["affine_lps"][0, 3] += 1
            else:
                broken["affine_lps"][0, 0] *= -1
            with self.assertRaisesRegex(ValueError, "空间网格"):
                viewer.load_dicom_series(self.series, expect_n=24, mask_geometry=broken)

    def test_mixed_series_is_rejected(self):
        path = self.series / "001.dcm"
        ds = pydicom.dcmread(path)
        ds.SeriesInstanceUID = pydicom.uid.generate_uid()
        ds.save_as(path, enforce_file_format=True)
        with self.assertRaisesRegex(ValueError, "一个有效"):
            viewer.load_dicom_series(self.series)

    def test_missing_sform_and_invalid_dimensions_are_rejected(self):
        original = gzip.decompress(self.mask_path.read_bytes())
        for offset, value in ((254, 0), (40, 4)):
            raw = bytearray(original)
            struct.pack_into("<h", raw, offset, value)
            self.mask_path.write_bytes(gzip.compress(raw))
            with self.assertRaises(ValueError):
                viewer.read_nifti_gz(self.mask_path)

    def test_reversed_stack(self):
        _, _, meta = viewer.read_nifti_gz(self.mask_path)
        affine = meta["affine_lps"].copy()
        affine[2, 2], affine[2, 3] = -2, 46
        volume, _ = viewer.load_dicom_series(self.series, expect_n=24, z_sign=-1,
            z0=46, mask_geometry=dict(meta, affine_lps=affine))
        np.testing.assert_array_equal(volume, self.pixels[::-1])


if __name__ == "__main__":
    unittest.main()
