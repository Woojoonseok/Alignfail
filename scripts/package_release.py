"""Package source + built UI, excluding all datasets, DBs and platform environments."""

import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app import __version__  # noqa: E402

EXCLUDED = {"node_modules", "__pycache__", ".pytest_cache", ".venv"}


def main():
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise SystemExit("Build the frontend first: npm --prefix frontend run build")
    paths = [
        ROOT / name
        for name in ["README.md", "TRAINING.md", "VALIDATION.md", "pytest.ini", ".gitignore", ".gitattributes"]
    ]
    for directory in ["backend", "frontend", "scripts", "training"]:
        paths.extend(
            p
            for p in (ROOT / directory).rglob("*")
            if p.is_file()
            and not EXCLUDED.intersection(p.relative_to(ROOT).parts)
            and p.suffix not in {".pyc", ".tsbuildinfo"}
        )
    destination = ROOT / f"artifacts/alignfail-dataset-studio-v{__version__}.zip"
    destination.parent.mkdir(exist_ok=True)
    with ZipFile(destination, "w", ZIP_DEFLATED) as bundle:
        for path in sorted(paths):
            bundle.write(path, "alignfail-dataset-studio/" + path.relative_to(ROOT).as_posix())
    print(f"Release: {destination}")
    print(f"Files: {len(paths)} / Size: {destination.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
