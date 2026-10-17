"""Auto-scan: turn what is in the repository into documentation pages, with no project-specific code.

Every scanner reads the checkout and returns Markdown that uses the same directives as hand-written
pages (`:::tree`, `:::network`, `:::chart` ...), so scanned pages look like the rest of the site.

Built-in scanners: overview, structure, modules (import graph), activity (git), dependencies
(package manifests), todos, documents. Add your own with `docs/site/scanners/*.py`:

    def scan(ctx):                      # ctx: root, files, config, read(path), run(*git_args)
        return [{"id": "routes", "title": "HTTP routes", "group": "Auto", "order": 330,
                 "summary": "…", "markdown": "…"}]
"""
from __future__ import annotations

import collections
import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LANG = {
    ".py": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin", ".cs": "C#", ".rb": "Ruby", ".php": "PHP",
    ".swift": "Swift", ".c": "C", ".h": "C", ".cc": "C++", ".cpp": "C++", ".hpp": "C++", ".m": "Objective-C", ".sh": "Shell",
    ".ps1": "PowerShell", ".sql": "SQL", ".html": "HTML", ".css": "CSS", ".scss": "CSS", ".vue": "Vue", ".svelte": "Svelte",
    ".md": "Markdown", ".yaml": "YAML", ".yml": "YAML", ".json": "JSON", ".toml": "TOML", ".dart": "Dart", ".lua": "Lua",
    ".ex": "Elixir", ".exs": "Elixir", ".scala": "Scala", ".r": "R", ".tf": "Terraform",
}
CODE = {"Python", "JavaScript", "TypeScript", "Go", "Rust", "Java", "Kotlin", "C#", "Ruby", "PHP", "Swift", "C", "C++",
        "Objective-C", "Shell", "PowerShell", "SQL", "Vue", "Svelte", "Dart", "Lua", "Elixir", "Scala", "R", "Terraform"}
SKIP_PARTS = {".git", "node_modules", "dist", "build", "venv", ".venv", "__pycache__", "target", ".next", "vendor", "coverage",
              ".idea", ".vscode", ".gradle", "out", ".cache", ".pytest_cache", ".mypy_cache", ".tox", "site-packages", ".studio"}
MAX_BYTES = 600_000


@dataclass
class Ctx:
    root: Path
    docs_dir: str
    config: dict[str, Any]
    files: list[str] = field(default_factory=list)
    _cache: dict[str, str] = field(default_factory=dict)

    def read(self, rel: str) -> str:
        if rel not in self._cache:
            try:
                p = self.root / rel
                self._cache[rel] = p.read_text(encoding="utf-8", errors="replace") if p.stat().st_size <= MAX_BYTES else ""
            except OSError:
                self._cache[rel] = ""
        return self._cache[rel]

    def run(self, *args: str, timeout: int = 30) -> str:
        try:
            out = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, timeout=timeout,
                                 check=False, encoding="utf-8", errors="replace")
            return out.stdout if out.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""


def list_files(root: Path, docs_dir: str, extra_ignore: list[str]) -> list[str]:
    out = ""
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                             capture_output=True, text=True, timeout=60, check=False, encoding="utf-8", errors="replace").stdout
    except (OSError, subprocess.SubprocessError):
        pass
    if out:
        files = [f for f in out.split("\0") if f]
    else:
        files = []
        for base, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_PARTS]
            for n in names:
                files.append(os.path.relpath(os.path.join(base, n), root).replace(os.sep, "/"))
    tooling = (f"{docs_dir}/site/", f"{docs_dir}/board/", f"{docs_dir}/.studio/", f"{docs_dir}/whiteboard/", f"{docs_dir}/netlify/")
    keep = []
    for f in files:
        parts = f.split("/")
        if any(p in SKIP_PARTS for p in parts[:-1]) or f.startswith(tooling) or not (root / f).is_file():
            continue
        if any(re.search(pat, f) for pat in extra_ignore):
            continue
        keep.append(f)
    return keep


def _loc(ctx: Ctx, rel: str) -> int:
    text = ctx.read(rel)
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _clean(text: str) -> str:
    return re.sub(r"\s*\|\s*", " / ", text.replace("\n", " ")).strip()


# --------------------------------------------------------------------------- #
# scanners: each returns a page dict                                           #
# --------------------------------------------------------------------------- #
def scan_overview(ctx: Ctx) -> dict | None:
    by_lang: collections.Counter = collections.Counter()
    files_by_lang: collections.Counter = collections.Counter()
    by_top: collections.Counter = collections.Counter()
    total = 0
    for f in ctx.files:
        lang = LANG.get(Path(f).suffix.lower())
        if lang not in CODE:
            continue
        n = _loc(ctx, f)
        by_lang[lang] += n
        files_by_lang[lang] += 1
        by_top[f.split("/")[0] if "/" in f else "(root)"] += n
        total += n
    if not total:
        return None
    commits = ctx.run("rev-list", "--count", "HEAD").strip()
    people = len({ln for ln in ctx.run("log", "--format=%an", "-n", "2000").splitlines() if ln})
    last = ctx.run("log", "-1", "--format=%cs").strip()
    tiles = [f"- Code files | {_fmt(sum(files_by_lang.values()))} | | | across {len(by_lang)} languages",
             f"- Lines of code | {_fmt(total)} | | | blank lines and comments included"]
    if commits:
        tiles.append(f"- Commits | {_fmt(int(commits))} | | | by {people} {'person' if people == 1 else 'people'}")
    if last:
        tiles.append(f"- Last commit | {last} | | | on the current branch")
    langs = by_lang.most_common(8)
    rest = total - sum(v for _k, v in langs)
    donut = [f"- {k} | {v} | {files_by_lang[k]} files" for k, v in langs] + ([f"- Other | {rest}"] if rest > 0 else [])
    tops = [f"- {k} | {v}" for k, v in by_top.most_common(10)]
    md = ("The numbers below are read from the repository every time the docs are built.\n\n"
          ":::stats 4\n" + "\n".join(tiles) + "\n:::\n\n"
          "## Languages by lines of code\n\n:::donut center=\"" + _fmt(total) + " lines\"\n" + "\n".join(donut) + "\n:::\n\n"
          "## Where the code lives\n\n:::bars\n" + "\n".join(tops) + "\n:::\n")
    return {"id": "scan-overview", "title": "Project at a glance", "group": "Auto", "order": 300,
            "summary": "Size, languages and activity, counted from the repository.", "markdown": md}


def scan_structure(ctx: Ctx) -> dict | None:
    tree: dict = {}
    for f in ctx.files:
        node = tree
        for part in f.split("/")[:-1][:3]:
            node = node.setdefault(part, {})
    counts: collections.Counter = collections.Counter()
    for f in ctx.files:
        p = f.split("/")
        for d in range(1, min(len(p), 4)):
            counts["/".join(p[:d])] += 1
    if not tree:
        return None
    lines: list[str] = ["Project"]
    budget = [70]

    def walk(node: dict, prefix: str, depth: int) -> None:
        for name in sorted(node, key=lambda n: -counts["/".join((prefix + "/" + n).strip("/").split("/"))]):
            if budget[0] <= 0:
                return
            budget[0] -= 1
            path = (prefix + "/" + name).strip("/")
            lines.append("  " * depth + f"{name}/ | {counts[path]} files")
            walk(node[name], path, depth + 1)

    walk(tree, "", 1)
    root_files = [f for f in ctx.files if "/" not in f][:6]
    md = ("Folders down to three levels, busiest first, with the number of files in each.\n\n:::tree lr\n" + "\n".join(lines) + "\n:::\n")
    if root_files:
        md += "\n:::details Files at the root\n" + "\n".join(f"- `{f}`" for f in root_files) + "\n:::\n"
    return {"id": "scan-structure", "title": "Folder structure", "group": "Auto", "order": 310,
            "summary": "How the repository is laid out.", "markdown": md}


def _module_of(path: str, depth: int) -> str:
    parts = path.split("/")
    return "/".join(parts[:depth]) if len(parts) > depth else (parts[0] if len(parts) > 1 else "(root)")


def scan_modules(ctx: Ctx) -> dict | None:
    src = [f for f in ctx.files if Path(f).suffix.lower() in (".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx")]
    if len(src) < 3:
        return None
    src = src[:4000]
    mods = {d: len({_module_of(f, d) for f in src}) for d in (1, 2, 3)}
    depth = next((d for d in (1, 2, 3) if mods[d] >= 6), 3 if mods[3] <= 40 else 2)
    if mods[depth] > 40:
        depth = max(1, depth - 1)
    py_index: dict[str, str] = {}
    for f in src:
        if f.endswith(".py"):
            stem = f[:-3]
            if stem.endswith("/__init__"):
                stem = stem[: -len("/__init__")]
            parts = stem.split("/")
            for i in range(len(parts)):
                py_index.setdefault(".".join(parts[i:]), f)
    edges: collections.Counter = collections.Counter()
    fileset = set(src)
    for f in src:
        text = ctx.read(f)
        mine = _module_of(f, depth)
        targets: set[str] = set()
        if f.endswith(".py"):
            for m in re.finditer(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", text, re.M):
                name = m.group(1) or m.group(2)
                parts = name.split(".")
                for k in range(len(parts), 0, -1):
                    hit = py_index.get(".".join(parts[:k]))
                    if hit:
                        targets.add(hit)
                        break
        else:
            for m in re.finditer(r"""(?:from\s+|require\(\s*|import\(\s*|import\s+)['"](\.{1,2}/[^'"]+)['"]""", text):
                rel = os.path.normpath(os.path.join(os.path.dirname(f), m.group(1))).replace(os.sep, "/")
                for cand in (rel, *(rel + e for e in (".ts", ".tsx", ".js", ".jsx", ".mjs")), *(rel + "/index" + e for e in (".ts", ".tsx", ".js"))):
                    if cand in fileset:
                        targets.add(cand)
                        break
        for t in targets:
            other = _module_of(t, depth)
            if other != mine:
                edges[(mine, other)] += 1
    if not edges:
        return None
    top = edges.most_common(45)
    names = {a for (a, _), _n in top} | {b for (_, b), _n in top}
    ids = {n: re.sub(r"[^A-Za-z0-9_]", "_", n) for n in names}
    lines = [f"node {ids[n]} | {n}" for n in sorted(names)]
    lines += [f"{ids[a]} -> {ids[b]}" + (f": {c}" if c > 1 else "") for (a, b), c in top]
    deg: collections.Counter = collections.Counter()
    for (a, b), c in top:
        deg[a] += c
        deg[b] += c
    busiest = ", ".join(f"`{n}`" for n, _c in deg.most_common(3))
    md = (f"Which parts of the code import which, grouped by folder (depth {depth}). An arrow means “imports from”; a number is how many "
          f"files do. Busiest modules: {busiest}.\n\n:::flow lr anim=packets\n" + "\n".join(lines) + "\n:::\n")
    return {"id": "scan-modules", "title": "Module dependencies", "group": "Auto", "order": 320,
            "summary": "Who imports whom, read from the source files.", "markdown": md}


def scan_activity(ctx: Ctx) -> dict | None:
    log = ctx.run("log", "-n", "400", "--format=%cs\t%an\t%s")
    if not log.strip():
        return None
    rows = [ln.split("\t", 2) for ln in log.splitlines() if ln.count("\t") >= 2]
    if not rows:
        return None
    import datetime as dt
    weeks: collections.Counter = collections.Counter()
    authors: collections.Counter = collections.Counter()
    for d, a, _s in rows:
        authors[a] += 1
        try:
            day = dt.date.fromisoformat(d)
        except ValueError:
            continue
        weeks[(day - dt.timedelta(days=day.weekday())).isoformat()] += 1
    keys = sorted(weeks)[-12:]
    md = "What changed recently, from the git history.\n\n"
    if len(keys) >= 2:
        md += ("## Commits per week\n\n:::chart column\nx: " + " | ".join(k[5:] for k in keys) + "\nseries Commits | "
               + " | ".join(str(weeks[k]) for k in keys) + "\n:::\n\n")
    if len(authors) > 1:
        md += "## Who commits\n\n:::donut\n" + "\n".join(f"- {_clean(a)} | {n}" for a, n in authors.most_common(6)) + "\n:::\n\n"
    md += "## Latest commits\n\n:::timeline\n" + "\n".join(f"- {d} | {_clean(s)[:90]} | by {_clean(a)}" for d, a, s in rows[:14]) + "\n:::\n"
    return {"id": "scan-activity", "title": "Recent activity", "group": "Auto", "order": 330,
            "summary": "Commits per week, contributors and the latest changes.", "markdown": md}


def _manifest_deps(ctx: Ctx) -> list[tuple[str, str, list[str]]]:
    found = []
    for f in ctx.files:
        name = Path(f).name
        if f.count("/") > 3:
            continue
        text = ctx.read(f) if name in ("package.json", "requirements.txt", "pyproject.toml", "go.mod", "Cargo.toml", "composer.json", "Gemfile", "pubspec.yaml") else ""
        if not text:
            continue
        deps: list[str] = []
        if name in ("package.json", "composer.json"):
            try:
                data = json.loads(text)
                deps = sorted({*data.get("dependencies", {}), *data.get("devDependencies", {}), *data.get("require", {})})
            except ValueError:
                pass
        elif name == "requirements.txt":
            deps = [re.split(r"[<>=!~\[; ]", ln.strip(), 1)[0] for ln in text.splitlines() if ln.strip() and not ln.startswith(("#", "-"))]
        elif name == "pyproject.toml":
            blk = re.search(r"dependencies\s*=\s*\[(.*?)\]", text, re.S)
            deps = [re.split(r"[<>=!~\[; ]", s.strip(" \"'"), 1)[0] for s in (blk.group(1).split(",") if blk else []) if s.strip(" \"'\n")]
        elif name == "go.mod":
            deps = re.findall(r"^\s*([\w./-]+\.[\w./-]+)\s+v", text, re.M)
        elif name == "Cargo.toml":
            blk = re.search(r"\[dependencies\](.*?)(?:\n\[|\Z)", text, re.S)
            deps = re.findall(r"^([\w-]+)\s*=", blk.group(1), re.M) if blk else []
        elif name == "Gemfile":
            deps = re.findall(r"^\s*gem\s+['\"]([^'\"]+)", text, re.M)
        elif name == "pubspec.yaml":
            blk = re.search(r"^dependencies:\n((?:[ \t]+.*\n?)+)", text, re.M)
            deps = re.findall(r"^\s{2}([\w_]+):", blk.group(1), re.M) if blk else []
        if deps:
            found.append((f, name, deps))
    return found


def scan_dependencies(ctx: Ctx) -> dict | None:
    found = _manifest_deps(ctx)
    if not found:
        return None
    md = "Third-party packages declared in the project's manifests.\n\n:::donut\n" + "\n".join(f"- {f} | {len(d)}" for f, _n, d in found[:8]) + "\n:::\n\n"
    for f, _n, deps in found[:8]:
        shown = ", ".join(f"`{d}`" for d in deps[:60]) + (f" and {len(deps) - 60} more" if len(deps) > 60 else "")
        md += f":::details {f} ({len(deps)})\n{shown}\n:::\n\n"
    return {"id": "scan-dependencies", "title": "Dependencies", "group": "Auto", "order": 340,
            "summary": "Packages declared in package.json, requirements, pyproject, go.mod and similar.", "markdown": md}


def scan_todos(ctx: Ctx) -> dict | None:
    pat = re.compile(r"(?:#|//|/\*|<!--|--)\s*(TODO|FIXME|HACK|XXX)\b[:\s(]*(.*)")
    rows = []
    for f in ctx.files:
        if LANG.get(Path(f).suffix.lower()) not in CODE:
            continue
        for i, line in enumerate(ctx.read(f).splitlines(), 1):
            m = pat.search(line)
            if m:
                rows.append((m.group(1), f"{f}:{i}", _clean(m.group(2))[:110]))
        if len(rows) >= 80:
            break
    if not rows:
        return None
    md = (f"{len(rows)}{'+' if len(rows) >= 80 else ''} markers found in the code.\n\n| Marker | Where | Note |\n|---|---|---|\n"
          + "\n".join(f"| {k} | `{w}` | {n or '—'} |" for k, w, n in rows[:80]) + "\n")
    return {"id": "scan-todos", "title": "Open TODOs", "group": "Auto", "order": 350,
            "summary": "TODO, FIXME and HACK comments left in the code.", "markdown": md}


def scan_documents(ctx: Ctx) -> dict | None:
    docs = [f for f in ctx.files if f.lower().endswith((".md", ".mdx", ".rst")) and not f.startswith(ctx.docs_dir + "/site/")][:60]
    if not docs:
        return None
    lines = []
    for f in docs:
        text = ctx.read(f)
        m = re.search(r"^#\s+(.+)$", text, re.M)
        title = _clean(m.group(1)) if m else Path(f).stem
        para = next((p.strip() for p in re.split(r"\n\s*\n", re.sub(r"^#.*$", "", text, flags=re.M)) if len(p.strip()) > 30 and not p.strip().startswith(("|", "```", ":::", "---"))), "")
        lines.append(f"- book | {title[:70]} | {_clean(para)[:130]} | `{f}`")
    md = "Markdown documents found in the repository, with the opening line of each.\n\n:::cards 3 mini\n" + "\n".join(lines) + "\n:::\n"
    return {"id": "scan-documents", "title": "Documents in the repo", "group": "Auto", "order": 360,
            "summary": "Every Markdown file outside the docs site, with its title and first lines.", "markdown": md}


BUILTIN = [scan_overview, scan_structure, scan_modules, scan_activity, scan_dependencies, scan_todos, scan_documents]


def load_custom(folder: Path) -> list:
    fns = []
    if folder.is_dir():
        for path in sorted(folder.glob("*.py")):
            if path.name.startswith("_"):
                continue
            spec = importlib.util.spec_from_file_location(f"scanner_{path.stem}", path)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = mod
                spec.loader.exec_module(mod)
                if hasattr(mod, "scan"):
                    fns.append(mod.scan)
    return fns


def run_all(root: Path, docs_dir: str, config: dict[str, Any], custom_dir: Path | None = None) -> tuple[list[dict], list[tuple[str, str, str]]]:
    """(pages, report rows). A scanner that fails is reported, never fatal."""
    scan_cfg = config.get("scan", {}) or {}
    if scan_cfg.get("enabled", True) is False:
        return [], [("scan", "skipped", "disabled in studio.json")]
    ctx = Ctx(root, docs_dir, config)
    ctx.files = list_files(root, docs_dir, scan_cfg.get("ignore", []))
    disabled = set(scan_cfg.get("disable", []))
    pages: list[dict] = []
    report: list[tuple[str, str, str]] = []
    for fn in BUILTIN + (load_custom(custom_dir) if custom_dir else []):
        name = fn.__name__.replace("scan_", "") if fn.__name__ != "scan" else "custom"
        if name in disabled:
            report.append((f"scan:{name}", "skipped", "disabled"))
            continue
        try:
            res = fn(ctx)
            res = [res] if isinstance(res, dict) else (res or [])
            pages.extend(res)
            report.append((f"scan:{name}", "ok" if res else "skipped", f"{len(res)} page(s)" if res else "nothing to show here"))
        except Exception as exc:                                                   # noqa: BLE001
            report.append((f"scan:{name}", "failed", f"{type(exc).__name__}: {exc}"))
    return pages, report
