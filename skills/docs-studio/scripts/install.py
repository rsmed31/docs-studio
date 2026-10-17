#!/usr/bin/env python3
"""Install (or update) docs-studio into a project. Run once; every later session starts the server by itself.

    python install.py [--project DIR] [--docs-dir docs] [--name "Project name"] [--port N]
                      [--no-session-hook] [--no-git-hook] [--no-start] [--uninstall]

What it does, in order:
  1. copies the runtime into <project>/<docs-dir>/ (site/, board/). Re-running updates the code and never
     touches your content: site/src, site/presets_custom, site/scanners, board/board.yaml, studio.json
  2. writes <docs-dir>/studio.json if missing, and ignores <docs-dir>/.studio/ in git
  3. registers a SessionStart hook in <project>/.claude/settings.json that starts the server
  4. adds a post-commit git hook that rebuilds the docs after every commit
  5. builds the site and starts the server

Prints one JSON object at the end so the caller can read the result.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parent / "runtime"
USER_OWNED = {"site/src", "site/presets_custom", "site/scanners", "board/board.yaml", "studio.json"}
MARK_BEGIN, MARK_END = "# >>> docs-studio >>>", "# <<< docs-studio <<<"


def git(root: Path, *args: str) -> str:
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30, check=False,
                             encoding="utf-8", errors="replace")
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def project_root(arg: str | None) -> Path:
    start = Path(arg).resolve() if arg else Path.cwd().resolve()
    top = git(start, "rev-parse", "--show-toplevel")
    return Path(top).resolve() if top else start


def py_command() -> str:
    for name in (("python", "python3", "py") if os.name == "nt" else ("python3", "python")):
        if shutil.which(name):
            return name
    return "python"


def ensure_yaml() -> str:
    try:
        import yaml  # noqa: F401
        return "present"
    except ImportError:
        pass
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--user", "pyyaml"], capture_output=True, text=True, check=False)
    return "installed" if r.returncode == 0 else "MISSING: run  python -m pip install pyyaml"


def copy_runtime(dest: Path) -> list[str]:
    changed = []
    for src in sorted(RUNTIME.rglob("*")):
        if not src.is_file() or "__pycache__" in src.parts or src.suffix == ".pyc":
            continue
        rel = src.relative_to(RUNTIME).as_posix()
        if rel.startswith("templates/"):
            continue
        if any(rel == u or rel.startswith(u + "/") for u in USER_OWNED) and (dest / rel).exists():
            continue
        target = dest / rel
        if target.exists() and target.read_bytes() == src.read_bytes():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        changed.append(rel)
    return changed


def seed_pages(docs: Path) -> list[str]:
    """Starter pages for the board and the whiteboard, once, unless the project already has them."""
    src_dir = docs / "site" / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    existing = "\n".join(f.read_text(encoding="utf-8", errors="replace")[:400] for f in src_dir.glob("*.md"))
    added = []
    for name, page_id in (("board.md", "board"), ("whiteboard.md", "whiteboard")):
        if f"id: {page_id}" in existing:
            continue
        shutil.copyfile(RUNTIME / "templates" / name, src_dir / f"8{len(added)}-{name}")
        added.append(name)
    return added


def write_config(docs: Path, name: str | None, port: int) -> None:
    path = docs / "studio.json"
    if path.exists():
        return
    cfg = {"name": name or docs.parent.name.replace("-", " ").replace("_", " ").title(), "port": port, "animation": "auto",
           "features": {"board": True, "whiteboard": True}, "scan": {"enabled": True, "ignore": [], "disable": []},
           "server": {"commit_edits": False}}
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def gitignore(root: Path, docs_name: str) -> None:
    gi = root / ".gitignore"
    entry = f"{docs_name}/.studio/"
    text = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if entry not in text.splitlines():
        gi.write_text(text + ("" if text.endswith("\n") or not text else "\n") + f"# docs-studio runtime state\n{entry}\n", encoding="utf-8")


def session_hook(root: Path, docs_name: str, remove: bool = False) -> str:
    path = root / ".claude" / "settings.json"
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return f"SKIPPED: {path} is not valid JSON; add the hook by hand"
    hooks = data.setdefault("hooks", {})
    groups = hooks.setdefault("SessionStart", [])
    needle = f"{docs_name}/site/studio.py hook session-start"
    for g in groups:
        g["hooks"] = [h for h in g.get("hooks", []) if needle not in h.get("command", "")]
    groups[:] = [g for g in groups if g.get("hooks")]
    if not remove:
        groups.append({"matcher": "startup|resume", "hooks": [{"type": "command", "command": f"{py_command()} {needle}", "timeout": 30}]})
    if not groups:
        hooks.pop("SessionStart")
    if not hooks:
        data.pop("hooks")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return "removed" if remove else f"registered in {path.relative_to(root).as_posix()}"


def hook_block(docs_name: str) -> str:
    return f"{MARK_BEGIN}\n{py_command()} {docs_name}/site/studio.py hook post-commit || true\n{MARK_END}\n"


def hooks_dir(root: Path) -> tuple[Path, bool]:
    """(directory to put post-commit in, whether it is a new versioned .githooks we point git at)."""
    configured = git(root, "config", "--get", "core.hooksPath")
    if configured:
        p = Path(configured)
        return (p if p.is_absolute() else root / p), False
    default = Path(git(root, "rev-parse", "--git-path", "hooks") or ".git/hooks")
    default = default if default.is_absolute() else root / default
    existing = [f for f in default.glob("*") if f.is_file() and not f.name.endswith(".sample")] if default.is_dir() else []
    if existing:
        return default, False
    return root / ".githooks", True


def git_hook(root: Path, docs_name: str, remove: bool = False) -> str:
    if not git(root, "rev-parse", "--git-dir"):
        return "SKIPPED: not a git repository"
    target_dir, point = hooks_dir(root)
    hook = target_dir / "post-commit"
    text = hook.read_text(encoding="utf-8") if hook.exists() else ""
    if MARK_BEGIN in text:
        pre, rest = text.split(MARK_BEGIN, 1)
        text = pre + rest.split(MARK_END, 1)[-1].lstrip("\n")
    if remove:
        if text.strip() in ("", "#!/bin/sh"):
            hook.unlink(missing_ok=True)
        else:
            hook.write_text(text, encoding="utf-8", newline="\n")
        return "removed"
    if not text.strip():
        text = "#!/bin/sh\n"
    elif not text.startswith("#!"):
        text = "#!/bin/sh\n" + text
    text = text.rstrip("\n") + "\n\n" + hook_block(docs_name)
    target_dir.mkdir(parents=True, exist_ok=True)
    hook.write_text(text, encoding="utf-8", newline="\n")
    try:
        hook.chmod(hook.stat().st_mode | 0o111)
    except OSError:
        pass
    if point:
        subprocess.run(["git", "-C", str(root), "config", "core.hooksPath", target_dir.relative_to(root).as_posix()], check=False)
    return f"post-commit in {target_dir.relative_to(root).as_posix() if target_dir.is_relative_to(root) else target_dir}" + (" (git pointed at it)" if point else "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project")
    ap.add_argument("--docs-dir", default="docs")
    ap.add_argument("--name")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--no-session-hook", action="store_true")
    ap.add_argument("--no-git-hook", action="store_true")
    ap.add_argument("--no-start", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    a = ap.parse_args()
    root = project_root(a.project)
    docs = root / a.docs_dir
    result: dict = {"project": str(root), "docs": str(docs)}
    if a.uninstall:
        result["session_hook"] = session_hook(root, a.docs_dir, remove=True)
        result["git_hook"] = git_hook(root, a.docs_dir, remove=True)
        subprocess.run([sys.executable, str(docs / "site" / "studio.py"), "stop"], check=False)
        result["note"] = f"hooks removed; {a.docs_dir}/ left in place (delete it by hand if you want it gone)"
        print(json.dumps(result, indent=2))
        return 0
    result["pyyaml"] = ensure_yaml()
    changed = copy_runtime(docs)
    result["runtime_files_written"] = len(changed)
    write_config(docs, a.name, a.port)
    result["seeded_pages"] = seed_pages(docs)
    gitignore(root, a.docs_dir)
    result["session_hook"] = "off" if a.no_session_hook else session_hook(root, a.docs_dir)
    result["git_hook"] = "off" if a.no_git_hook else git_hook(root, a.docs_dir)
    studio = [sys.executable, str(docs / "site" / "studio.py")]
    build = subprocess.run([*studio, "build"], cwd=str(root), capture_output=True, text=True, check=False)
    result["build"] = (build.stdout.strip() or build.stderr.strip()).splitlines()[-3:]
    if not a.no_start:
        start = subprocess.run([*studio, "start"], cwd=str(root), capture_output=True, text=True, check=False)
        result["server"] = (start.stdout.strip() or start.stderr.strip())
    pages = sorted(p.name for p in (docs / "site" / "src").glob("*.md")) if (docs / "site" / "src").is_dir() else []
    result["written_pages"] = pages
    result["next"] = ("write the project's pages into " + f"{a.docs_dir}/site/src/*.md (see references/authoring.md), then run: "
                      f"{py_command()} {a.docs_dir}/site/studio.py build") if not pages else "pages exist: use `refresh` to update them"
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
