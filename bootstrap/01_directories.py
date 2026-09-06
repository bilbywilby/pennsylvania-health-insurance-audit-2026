#!/usr/bin/env python3
"""Creates the complete directory skeleton and privacy gitignore (idempotent)."""
from pathlib import Path

DIRS = [
    "audit", "data", "data/public", "data/private",
    "docs", "docs/figures", "tests", "tests/fixtures",
    ".github/workflows", "scripts",
]


def main():
    print("Creating directory structure...")
    for d in DIRS:
        path = Path(d)
        path.mkdir(parents=True, exist_ok=True)
        print(f"[OK] {path}/")

    private_gitignore = Path("data/private/.gitignore")
    if not private_gitignore.exists():
        private_gitignore.write_text("*\n!.gitignore\n", encoding="utf-8")
        print("[OK] data/private/.gitignore created")
    else:
        print("[SKIP] data/private/.gitignore already exists")

    root_gitignore = Path(".gitignore")
    content = (
        ".env\n"
        "__pycache__/\n"
        ".pytest_cache/\n"
        "data/private/*\n"
        "!data/private/.gitignore\n"
        "*.age\n"
        "*.age.asc\n"
        "*.pyc\n"
        "*.pyo\n"
        "*.log\n"
    )
    if not root_gitignore.exists():
        root_gitignore.write_text(content, encoding="utf-8")
        print("[OK] .gitignore created")
    else:
        print("[SKIP] .gitignore already exists")

    print("Directory setup complete.")


if __name__ == "__main__":
    main()
