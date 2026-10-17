// Assemble the hub's static site into public/: the hub pages, plus the docs theme and whiteboard from the
// skill runtime (one copy in the repo, shared by the local docs site and the hub).
import { cpSync, rmSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const runtime = here("../skills/docs-studio/runtime/site/");
rmSync(here("public"), { recursive: true, force: true });
mkdirSync(here("public"), { recursive: true });
cpSync(here("site"), here("public/hub"), { recursive: true });
cpSync(runtime + "theme", here("public/theme"), { recursive: true });
cpSync(runtime + "whiteboard", here("public/whiteboard"), { recursive: true });
console.log("hub built into public/");
