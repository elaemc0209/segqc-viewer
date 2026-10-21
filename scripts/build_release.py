"""Build a Windows release from this checkout, with licenses and synthetic demo."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from segqc_viewer import VERSION
from create_demo import create_demo


def run(*args):
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    if "PyInstaller" in args:
        # Resolve native dependencies from the audited Python environment only.
        system_root = os.environ["SystemRoot"]
        env["PATH"] = os.pathsep.join((str(Path(sys.executable).parent), sys.base_prefix,
            str(Path(sys.base_prefix) / "DLLs"), str(Path(system_root) / "System32"),
            system_root))
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True, env=env)


def main():
    run("scripts/collect_licenses.py", "--verify-existing")
    run("-m", "unittest", "discover", "-s", "tests", "-v")
    run("-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--noupx", "--name", "segqc-viewer", "--distpath", "dist", "src/segqc_viewer.py")
    bundle = ROOT / "release" / f"segqc-viewer-v{VERSION}-windows-x64"
    if bundle.exists():
        expected = (ROOT / "release").resolve()
        if bundle.resolve().parent != expected or not bundle.name.startswith("segqc-viewer-v"):
            raise RuntimeError("Refusing to replace a bundle outside the release directory")
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True, exist_ok=True)
    for name in ("LICENSE", "README.md", "README_zh.md", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, bundle / name)
    shutil.copytree(ROOT / "licenses", bundle / "licenses", dirs_exist_ok=True)
    shutil.copytree(ROOT / "docs", bundle / "docs", dirs_exist_ok=True)
    shutil.copy2(ROOT / "dist/segqc-viewer.exe", bundle / "segqc-viewer.exe")
    create_demo(bundle)
    (bundle / "DEMO_DATA.txt").write_text(
        "The included synthetic_case CT and mask are artificial. No patient data is included.\n"
        "Remove the demo folders before configuring your own data.\n", encoding="utf-8")
    manifest = {str(p.relative_to(bundle)).replace("\\", "/"):
                hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(bundle.rglob("*")) if p.is_file()}
    (bundle / "SHA256SUMS.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    archive = Path(shutil.make_archive(str(bundle), "zip", bundle.parent, bundle.name))
    archive.with_suffix(".zip.sha256").write_text(
        hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n", encoding="ascii")
    print(archive)


if __name__ == "__main__":
    main()
