# Release verification record

Copy this template into a release record and fill it with actual evidence. An unchecked item is not a claim of completion.

- Release version/tag:
- Source commit:
- Build date and operating system:
- Python version and distribution:
- Dependency lock/snapshot file:
- Reviewer:

## Source and data boundaries

- [ ] Source changes reviewed; original research data remains outside the public tree.
- [ ] Tracked files and proposed archive inspected for images, masks, patient identifiers, real case metadata, review results, local settings, credentials, and identifying screenshots.
- [ ] Git history checked for the same material before pushing.
- [ ] Case-count messages and defaults describe the public implementation accurately.
- [ ] README commands match the release's argument parser and file locations.

## Software checks

- [ ] `python -m unittest discover -s tests -v` passed; record the result and test scope.
- [ ] Source compiles; `--help` exits successfully without opening a review window.
- [ ] A synthetic example loads with the expected orientation and overlay.
- [ ] Slice navigation, overlay modes, window adjustment, grades, and note entry checked.
- [ ] CSV contents, restart/resume behavior, and output directory checked.
- [ ] Missing data, shape mismatch, and competing-series failures checked.
- [ ] Any real-data validation is separately recorded with permitted identifiers and explicit coverage; synthetic checks are not described as clinical validation.

## Licenses and binary release

- [ ] Project copyright holder and MIT authorization confirmed.
- [ ] Exact installed package/runtime versions and licenses recorded.
- [ ] Third-party notices include Python/Tcl/Tk, imaging dependencies, PyInstaller, and actual bundled native libraries.
- [ ] Source archive and binary archive contain applicable notices and license texts.
- [ ] Build performed from the stated source commit in the recorded environment.
- [ ] Executable starts outside the development directory; synthetic input and saved output checked.
- [ ] Executable/ZIP filenames, sizes, and SHA-256 hashes recorded.
- [ ] Release notes distinguish automated tests, GUI smoke checks, and unverified limitations.

## Publication

- [ ] Public repository contents and visibility checked after push.
- [ ] Tag resolves to the intended commit.
- [ ] Release assets match the recorded hashes and contain no private data.
- [ ] Download and extraction checked; source and binary usage instructions remain accurate.
