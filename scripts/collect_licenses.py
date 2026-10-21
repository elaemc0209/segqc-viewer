"""Collect exact installed license texts; abort rather than publish missing notices."""
from __future__ import annotations

import hashlib
import argparse
import importlib.metadata as metadata
import json
from pathlib import Path
import re
import ssl
import sys
import tkinter
import urllib.request
import zlib

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "licenses"
RUNTIME = ("numpy", "pydicom", "pillow")
BUILD = ("pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "packaging",
         "pefile", "pywin32-ctypes", "setuptools")
RECORDS = []


def save(relative: str, data: bytes, source: str) -> str:
    if len(data) < 30 or b"<html" in data[:200].lower():
        raise ValueError(f"Invalid license text: {source}")
    target = OUT / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    RECORDS.append({"file": target.relative_to(ROOT).as_posix(),
                    "sha256": hashlib.sha256(data).hexdigest(), "source": source})
    return target.relative_to(ROOT).as_posix()


def download(relative: str, url: str) -> str:
    # A failed refresh must stop the release, even if an older file is present.
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(3):
        try:
            opener = direct.open if attempt != 1 else urllib.request.urlopen
            with opener(url, timeout=25) as response:
                return save(relative, response.read(), url)
        except (OSError, ValueError):
            if attempt == 2:
                raise RuntimeError(f"Required license download failed: {url}")


def check_environment() -> None:
    if sys.version_info[:3] != (3, 12, 10):
        raise RuntimeError("Native license pins require official CPython 3.12.10; review before changing.")
    tcl_version = tkinter.Tcl().eval("info patchlevel")
    if tcl_version != "8.6.15" or zlib.ZLIB_VERSION != "1.3.1":
        raise RuntimeError("Tcl/zlib version differs from audited native license pins.")
    if not ssl.OPENSSL_VERSION.startswith("OpenSSL 3.0.16 "):
        raise RuntimeError("OpenSSL version differs from audited native license pin.")


def verify_existing() -> None:
    """Verify the audited local texts and exact build versions without networking."""
    check_environment()
    manifest = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    if manifest["python"] != sys.version.split()[0] or manifest["platform"] != sys.platform:
        raise RuntimeError("Manifest Python/platform differs from this build environment.")
    packages = {item["name"]: item for item in manifest["packages"]}
    if set(packages) != set(RUNTIME + BUILD):
        raise RuntimeError("Manifest package set differs from the required dependencies.")
    entries = {item["file"]: item for item in manifest["files"]}
    if len(entries) != len(manifest["files"]) or not entries:
        raise RuntimeError("Duplicate or empty license manifest.")
    for name, package in packages.items():
        if metadata.version(name) != package["version"]:
            raise RuntimeError(f"Installed {name} version differs from audited manifest.")
        if not package["license_files"] or not set(package["license_files"]) <= entries.keys():
            raise RuntimeError(f"Missing manifest license entries for {name}.")
    required_native = {"python/LICENSE.txt", "python/stdlib-license.rst",
                       "python/native-version-pins.bat", "tcl/license.terms",
                       "tk/license.terms", "zlib/LICENSE", "xz/COPYING", "openssl/LICENSE.txt"}
    if not {f"licenses/{name}" for name in required_native} <= entries.keys():
        raise RuntimeError("Missing native license entries in manifest.")
    for relative, entry in entries.items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(OUT.resolve()):
            raise RuntimeError(f"License manifest path outside licenses/: {relative}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise RuntimeError(f"License SHA-256 mismatch: {relative}")
    if not (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8").strip():
        raise RuntimeError("Missing third-party notices.")
    print(f"Verified {len(entries)} existing license/provenance files and {len(packages)} package versions offline.")


def collect() -> None:
    check_environment()
    rows = []
    packages = []
    for group, names in (("Runtime", RUNTIME), ("Build only", BUILD)):
        for name in names:
            dist = metadata.distribution(name)
            copied = []
            for item in dist.files or []:
                # This also retains notices from bundled native and vendored dependencies.
                if re.match(r"^(license|copying|notice|authors)([._-]|$)", item.name, re.I):
                    path = Path(dist.locate_file(item))
                    if not path.is_file():
                        raise FileNotFoundError(path)
                    copied.append(save(f"{name}/{item.as_posix()}", path.read_bytes(),
                                       f"Installed {name} {dist.version} wheel: {item.as_posix()}"))
            if not copied:
                raise RuntimeError(f"No license texts found for {name}")
            packages.append({"name": name, "version": dist.version, "scope": group,
                             "license_files": copied})
            rows.append(f"| {name} | {dist.version} | {group} | [license texts](licenses/{name}/) |")

    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    save("python/LICENSE.txt", python_license.read_bytes(), "Official CPython Windows 3.12.10 LICENSE.txt")
    base = "https://raw.githubusercontent.com/"
    native_sources = {
        "python/stdlib-license.rst": base + "python/cpython/v3.12.10/Doc/license.rst",
        "python/native-version-pins.bat": base + "python/cpython/v3.12.10/PCbuild/get_externals.bat",
        "tcl/license.terms": base + "tcltk/tcl/core-8-6-15/license.terms",
        "tk/license.terms": base + "tcltk/tk/core-8-6-15/license.terms",
        "zlib/LICENSE": base + "madler/zlib/v1.3.1/LICENSE",
        "xz/COPYING": base + "python/cpython-source-deps/xz-5.2.5/COPYING",
        "openssl/LICENSE.txt": base + "openssl/openssl/openssl-3.0.16/LICENSE.txt",
    }
    for relative, url in native_sources.items():
        download(relative, url)

    text = """# Third-party notices

The project MIT license applies to its original code. Third-party software
retains the licenses and copyrights reproduced in `licenses/`.
Keep this file and the entire `licenses/` directory with redistributed binaries.
The archive contains the complete license texts copied from the installed wheels,
including their native libraries and bundled notices. This inventory is generated
by `scripts/collect_licenses.py`; `licenses/manifest.json` records text provenance
and SHA-256 hashes. Build tools are separately identified below.

| Component | Version | Scope | Notices |
|---|---|---|---|
""" + "\n".join(rows) + """
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
"""
    (ROOT / "THIRD_PARTY_NOTICES.md").write_text(text, encoding="utf-8")
    manifest = {"python": sys.version.split()[0], "platform": sys.platform,
                "packages": packages, "files": RECORDS}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for entry in RECORDS:
        assert hashlib.sha256((ROOT / entry["file"]).read_bytes()).hexdigest() == entry["sha256"]
    print(f"Collected and hash-verified {len(RECORDS)} license/provenance files for {len(packages)} packages.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-existing", action="store_true",
                        help="Verify audited notices and environment without downloading.")
    args = parser.parse_args()
    if args.verify_existing:
        verify_existing()
    else:
        collect()
