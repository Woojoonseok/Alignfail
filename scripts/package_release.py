"""Package source + built UI, excluding all datasets, DBs and platform environments."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {"node_modules", "__pycache__", ".pytest_cache", ".venv"}


def main():
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise SystemExit("Build the frontend first: npm --prefix frontend run build")
    paths = [ROOT / name for name in ["README.md", "VALIDATION.md", "pytest.ini", ".gitignore", ".gitattributes"]]
    for directory in ["backend", "frontend", "scripts"]:
        paths.extend(p for p in (ROOT / directory).rglob("*")
                     if p.is_file() and not EXCLUDED.intersection(p.relative_to(ROOT).parts)
                     and p.suffix not in {".pyc", ".tsbuildinfo"})
    destination = ROOT / "artifacts/alignfail-dataset-studio-v0.1.0.zip"
    destination.parent.mkdir(exist_ok=True)
    with ZipFile(destination, "w", ZIP_DEFLATED) as bundle:
        for path in sorted(paths):
            bundle.write(path, "alignfail-dataset-studio/" + path.relative_to(ROOT).as_posix())
    print(f"Release: {destination}")
    print(f"Files: {len(paths)} / Size: {destination.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
