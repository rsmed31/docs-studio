#!/usr/bin/env node
"use strict";
// docs-studio installer: puts the skill in ~/.claude/skills/docs-studio (Claude Code) and/or
// ~/.codex/skills/docs-studio (Codex) and, with `init`, sets the current project up in one go.

const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const PKG = path.resolve(__dirname, "..");
const VERSION = require(path.join(PKG, "package.json")).version;
const DEST = {
  claude: path.join(process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude"), "skills", "docs-studio"),
  codex: path.join(process.env.CODEX_HOME || path.join(os.homedir(), ".codex"), "skills", "docs-studio"),
};
const PAYLOAD = ["SKILL.md", "README.md", "LICENSE", "scripts", "runtime", "references"];
const FLAGS = ["--claude", "--codex", "--all"];

const HELP = `docs-studio ${VERSION}: living documentation for any project, as an agent skill

Usage:
  npx docs-studio              install (or update) the skill for Claude Code   -> ${DEST.claude}
  npx docs-studio --codex      install it for Codex                            -> ${DEST.codex}
  npx docs-studio --all        install it for both
  npx docs-studio init         install the skill, then set up the project in the current folder
  npx docs-studio uninstall    remove the skill (a project's docs/ folder is left alone)
  npx docs-studio path         print where the skill is installed

Add --claude, --codex or --all to any command (default: --claude).
Options after \`init\` go to the project installer, e.g.:
  npx docs-studio init --name "My project" --docs-dir docs --no-git-hook

Then open your agent in a project and say: document this project with docs-studio`;

function copyDir(src, dst) {
  fs.mkdirSync(dst, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (entry.name === "__pycache__" || entry.name.endsWith(".pyc")) continue;
    const s = path.join(src, entry.name);
    const d = path.join(dst, entry.name);
    if (entry.isDirectory()) copyDir(s, d);
    else fs.copyFileSync(s, d);
  }
}

function installSkill(target) {
  const existed = fs.existsSync(target);
  fs.mkdirSync(target, { recursive: true });
  for (const item of PAYLOAD) {
    const src = path.join(PKG, item);
    if (!fs.existsSync(src)) continue;
    const dst = path.join(target, item);
    fs.rmSync(dst, { recursive: true, force: true });
    if (fs.statSync(src).isDirectory()) copyDir(src, dst);
    else fs.copyFileSync(src, dst);
  }
  console.log(`${existed ? "Updated" : "Installed"} the docs-studio skill ${VERSION} in ${target}`);
}

function python() {
  for (const cmd of process.platform === "win32" ? ["python", "py", "python3"] : ["python3", "python"]) {
    if (spawnSync(cmd, ["--version"], { stdio: "ignore" }).status === 0) return cmd;
  }
  return null;
}

function runInstaller(target, args) {
  const py = python();
  if (!py) {
    console.error("Python 3.9+ was not found on PATH. Install it, then run: npx docs-studio init");
    process.exit(1);
  }
  const r = spawnSync(py, [path.join(target, "scripts", "install.py"), "--project", process.cwd(), ...args], { stdio: "inherit" });
  process.exit(r.status === null ? 1 : r.status);
}

const argv = process.argv.slice(2);
const picked = argv.filter((a) => FLAGS.includes(a));
const [cmd, ...rest] = argv.filter((a) => !FLAGS.includes(a));
const targets = picked.includes("--all") ? ["claude", "codex"] : picked.includes("--codex") ? ["codex"] : ["claude"];
const agentName = targets.length === 2 ? "your agent" : targets[0] === "codex" ? "Codex" : "Claude Code";

switch (cmd) {
  case undefined:
  case "install":
  case "update":
    targets.forEach((t) => installSkill(DEST[t]));
    console.log(`\nNext: open ${agentName} in a project and say "document this project with docs-studio"\n(or run \`npx docs-studio init${picked.length ? " " + picked[0] : ""}\` in the project to set it up right now).`);
    break;
  case "init":
    targets.forEach((t) => installSkill(DEST[t]));
    // SessionStart hooks are a Claude Code feature: a Codex-only install registers the git hook only
    runInstaller(DEST[targets[0]], targets.includes("claude") ? rest : ["--no-session-hook", ...rest]);
    break;
  case "uninstall":
    targets.forEach((t) => {
      fs.rmSync(DEST[t], { recursive: true, force: true });
      console.log(`Removed ${DEST[t]}`);
    });
    console.log("To remove a project's hooks first, run in that project:\n  python <skill>/scripts/install.py --project . --uninstall");
    break;
  case "path":
    targets.forEach((t) => console.log(DEST[t]));
    break;
  case "-h":
  case "--help":
  case "help":
    console.log(HELP);
    break;
  case "-v":
  case "--version":
    console.log(VERSION);
    break;
  default:
    console.error(`Unknown command: ${cmd}\n`);
    console.log(HELP);
    process.exit(2);
}
