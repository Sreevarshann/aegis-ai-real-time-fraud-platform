#!/usr/bin/env node
// Render every ```mermaid block in README.md and docs/**/*.md with the real Mermaid CLI (headless Chromium).
// Fails with file:line and the parser error if any diagram does not render.
//
//   node scripts/check_mermaid.mjs            # uses @mermaid-js/mermaid-cli via npx
//   MMDC=/path/to/mmdc node scripts/check_mermaid.mjs
import { execFileSync } from "node:child_process";
import { mkdtempSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const MERMAID_CLI = "@mermaid-js/mermaid-cli@11.17.0";

function markdownFiles() {
  const files = [join(ROOT, "README.md")];
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name);
      if (statSync(p).isDirectory()) walk(p);
      else if (name.endsWith(".md")) files.push(p);
    }
  };
  walk(join(ROOT, "docs"));
  return files;
}

function blocks(file) {
  const lines = readFileSync(file, "utf8").split("\n");
  const found = [];
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim() === "```mermaid") {
      const start = i + 1;
      const body = [];
      while (++i < lines.length && lines[i].trim() !== "```") body.push(lines[i]);
      found.push({ line: start, source: body.join("\n") });
    }
  }
  return found;
}

const work = mkdtempSync(join(tmpdir(), "mermaid-check-"));
const puppeteerConfig = join(work, "puppeteer.json");
writeFileSync(puppeteerConfig, JSON.stringify({ args: ["--no-sandbox", "--disable-setuid-sandbox"] }));
const mmdc = process.env.MMDC ? [process.env.MMDC] : ["npx", "-y", "-p", MERMAID_CLI, "mmdc"];

let total = 0;
const failures = [];
for (const file of markdownFiles()) {
  for (const [n, block] of blocks(file).entries()) {
    total += 1;
    const input = join(work, `diagram-${total}.mmd`);
    writeFileSync(input, block.source);
    const where = `${relative(ROOT, file)}:${block.line}`;
    const kind = block.source.trim().split(/\s/)[0];
    try {
      execFileSync(mmdc[0], [...mmdc.slice(1), "-q", "-p", puppeteerConfig, "-i", input, "-o", join(work, `diagram-${total}.svg`)],
        { stdio: ["ignore", "pipe", "pipe"] });
      console.log(`  ok    ${where}  (${kind}, block ${n + 1})`);
    } catch (err) {
      const msg = String(err.stderr || err.message).split("\n").filter((l) => l.trim()).slice(0, 6).join("\n        ");
      failures.push(where);
      console.log(`  FAIL  ${where}  (${kind}, block ${n + 1})\n        ${msg}`);
    }
  }
}
console.log(`\n${total - failures.length}/${total} Mermaid diagrams rendered.`);
if (total === 0) console.log("No Mermaid diagrams found.");
process.exit(failures.length ? 1 : 0);
