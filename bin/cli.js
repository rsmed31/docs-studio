#!/usr/bin/env node
"use strict";
// docs-studio installer: puts the Claude Code skill in ~/.claude/skills/docs-studio
// and (with `init`) sets the current project up in one go.

const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const PKG = path.resolve(__dirname, "..");
const VERSION = require(path.join(PKG, "package.json")).version;
const CONFIG = process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude");
const TARGET = path.join(CONFIG, "skills", "docs-studio");
const PAYLOAD = ["SKILL.md", "README.md", "scripts", "runtime", "references"];

const HELP = `docs-studio ${VERSION}: living documentation for any project, as a Claude Code skill

Usage:
  npx docs-studio              install (or update) the skill into ${TARGET}
  npx docs-studio init         install the skill, then set up the project in the current folder
  npx docs-studio uninstall    remove the skill (a project's docs/ folder is left alone)
  npx docs-studio path         print where the skill is installed

Options for init are passed to the installer, e.g.:
  npx docs-studio init --name "My project" --docs-dir docs --no-git-hook

After installing, open Claude Code in a project and say: document this project with docs-studio`;

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

function installSkill() {
  const existed = fs.existsSync(TARGET);
  fs.mkdirSync(TARGET, { recursive: true });
  for (const item of PAYLOAD) {
    const src = path.join(PKG, item);
    if (!fs.existsSync(src)) continue;
    const dst = path.join(TARGET, item);
    fs.rmSync(dst, { recursive: true, force: true });
    if (fs.statSync(src).isDirectory()) copyDir(src, dst);
    else fs.copyFileSync(src, dst);
  }
  console.log(`${existed ? "Updated" : "Installed"} the docs-studio skill ${VERSION} in ${TARGET}`);
}

function python() {
  for (const cmd of process.platform === "win32" ? ["python", "py", "python3"] : ["python3", "python"]) {
    const r = spawnSync(cmd, ["--version"], { stdio: "ignore" });
    if (r.status === 0) return cmd;
  }
  return null;
}

function runInstaller(args) {
  const py = python();
  if (!py) {
    console.error("Python 3.9+ was not found on PATH. Install it, then run: npx docs-studio init");
    process.exit(1);
  }
  const script = path.join(TARGET, "scripts", "install.py");
  const r = spawnSync(py, [script, "--project", process.cwd(), ...args], { stdio: "inherit" });
  process.exit(r.status === null ? 1 : r.status);
}

const [cmd, ...rest] = process.argv.slice(2);
switch (cmd) {
  case undefined:
  case "install":
  case "update":
    installSkill();
    console.log("\nNext: open Claude Code in a project and say \"document this project with docs-studio\"\n(or run `npx docs-studio init` in the project to set it up right now).");
    break;
  case "init":
    installSkill();
    runInstaller(rest);
    break;
  case "uninstall":
    fs.rmSync(TARGET, { recursive: true, force: true });
    console.log(`Removed ${TARGET}. To remove a project's hooks first, run in that project:\n  python <skill>/scripts/install.py --project . --uninstall`);
    break;
  case "path":
    console.log(TARGET);
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
