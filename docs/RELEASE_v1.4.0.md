# v1.4.0 verification record

Date: 2026-10-21 (Asia/Singapore). Platform: Windows 11 x64.
Author/copyright: JQ (elaemc0209), 3360168387@qq.com. Project license: MIT.

This public edition was prepared independently from the original research
distribution. The existing research application and patient data were not modified.

## Changes reviewed

- Stop navigation and closure while CSV changes cannot be saved; preserve the
  in-memory changes for retry. Corrupt existing CSV files cannot be overwritten.
- Validate three-dimensional NIfTI-1 sform geometry in millimetres against every
  selected DICOM slice. Reject shifts, mirrors, mixed series and unsupported metadata.
- Support explicit CT, mask and output directories. Remove dataset-specific
  drive discovery and fixed case counts.
- Pin runtime/build packages and include full third-party license texts.

## Checks actually performed

- 11 unittest cases passed, including a real Tk desktop integration test.
- Synthetic CT HU values and mask voxels matched exactly after reading.
- Reversed stacks, same-shape shifted/mirrored masks, missing sform, invalid
  dimensions and competing SeriesInstanceUIDs were tested.
- CSV roundtrip, repeated failed writes and successful retry, invalid CSV
  preservation, navigation/close blocking, notes and restart/resume were tested.
- Tk fill/outline/hidden modes, slice changes, grade and note entry were exercised.
- Python syntax compilation and CLI help passed.
- 54 license/provenance files and 10 package versions passed SHA-256 and version
  checks. The build uses official CPython 3.12.10, not Anaconda.
- PyInstaller binary dependency paths were checked: audited Python and NumPy
  environment only; no Anaconda or unrelated local native runtime directories.
- The release ZIP passed CRC and per-file SHA-256 checks after extraction to a
  temporary directory. Its executable loaded the synthetic data from there,
  rendered the overlay, saved a minor grade and exited successfully.
- The resulting synthetic-window screenshot was visually inspected. It is the
  only screenshot included in this repository.

## Limits

No new real-patient or clinical validation was performed. This edition has
stricter geometry requirements than the original cohort-specific viewer and may
reject legacy masks with incomplete or inconsistent spatial metadata.
No automatic registration or resampling is performed. qform-only files,
multiframe CT and compressed transfer syntaxes needing optional decoders are
outside this release's tested scope. Windows binaries are unsigned. An independent
clean computer, alternate Windows versions and other operating systems were not tested.

The GitHub release tag identifies the published source commit. Asset hashes are
provided alongside the downloadable ZIP; internal hashes are in SHA256SUMS.json.
