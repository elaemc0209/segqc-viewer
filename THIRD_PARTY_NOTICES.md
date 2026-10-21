# Third-party notices

The project MIT license applies to its original code. Third-party software
retains the licenses and copyrights reproduced in `licenses/`.
Keep this file and the entire `licenses/` directory with redistributed binaries.
The archive contains the complete license texts copied from the installed wheels,
including their native libraries and bundled notices. This inventory is generated
by `scripts/collect_licenses.py`; `licenses/manifest.json` records text provenance
and SHA-256 hashes. Build tools are separately identified below.

| Component | Version | Scope | Notices |
|---|---|---|---|
| numpy | 2.5.4 | Runtime | [license texts](licenses/numpy/) |
| pydicom | 3.0.2 | Runtime | [license texts](licenses/pydicom/) |
| pillow | 13.0.0 | Runtime | [license texts](licenses/pillow/) |
| pyinstaller | 6.22.3 | Build only | [license texts](licenses/pyinstaller/) |
| pyinstaller-hooks-contrib | 2026.9 | Build only | [license texts](licenses/pyinstaller-hooks-contrib/) |
| altgraph | 0.17.5 | Build only | [license texts](licenses/altgraph/) |
| packaging | 26.3 | Build only | [license texts](licenses/packaging/) |
| pefile | 2024.8.26 | Build only | [license texts](licenses/pefile/) |
| pywin32-ctypes | 0.2.3 | Build only | [license texts](licenses/pywin32-ctypes/) |
| setuptools | 84.2.1 | Build only | [license texts](licenses/setuptools/) |
| CPython, standard library and Microsoft runtime notices | 3.12.10 | Runtime | [Windows license](licenses/python/LICENSE.txt), [stdlib notices](licenses/python/stdlib-license.rst) |
| Tcl | 8.6.15 | Runtime | [license](licenses/tcl/license.terms) |
| Tk | 8.6.15 | Runtime | [license](licenses/tk/license.terms) |
| zlib | 1.3.1 | Runtime | [license](licenses/zlib/LICENSE) |
| liblzma (XZ Utils library) | 5.2.5 | Runtime if collected | [public domain/library notice](licenses/xz/COPYING) |
| OpenSSL | 3.0.16 | Runtime if collected | [license](licenses/openssl/LICENSE.txt) |

The native version pins are from the official CPython 3.12.10 Windows build
[dependency script](licenses/python/native-version-pins.bat). CPython's Windows
license includes bzip2, libffi and Microsoft Distributable Code notices. Python
and its native libraries are bundled without changes; the application code is
separate. The executable targets Microsoft Windows; Microsoft runtime terms are
retained in the CPython Windows license.

NumPy's complete wheel license includes OpenBLAS, LAPACK and the GCC runtime
license with its GCC Runtime Library Exception. The exception is retained;
the main project MIT license does not replace those terms.

Pydicom includes the GDCM private-dictionary notice. Pillow's complete wheel
license includes its image codec and font library notices, including FreeType
and Independent JPEG Group notices. Portions of this software are copyright
of The FreeType Project (www.freetype.org). All rights reserved.
This software is based in part on the work of the Independent JPEG Group.
FreeType is used under the FreeType License (FTL) option reproduced with Pillow.

PyInstaller and its hooks are build tools. Its bootloader exception allows
distribution of the generated executable under the application's license,
subject to all dependency licenses. We include its complete license as a
courtesy; this does not relicense application code under GPL.
See [PyInstaller's official explanation](https://pyinstaller.org/en/stable/license.html).
Build tools and dependencies have not been modified.
