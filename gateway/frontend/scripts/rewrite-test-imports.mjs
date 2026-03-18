import fs from "node:fs";
import path from "node:path";

function isFile(p) {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
}

function walk(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else out.push(full);
  }
  return out;
}

function hasKnownExtension(spec) {
  return /\.(js|mjs|cjs|json|node)$/i.test(spec);
}

function rewriteImportsInFile(filePath) {
  const original = fs.readFileSync(filePath, "utf8");
  let changed = original;

  const patterns = [
    // import x from "./mod";
    { re: /(\bfrom\s+["'])(\.{1,2}\/[^"']+?)(["'])/g, group: 2 },
    // import "./mod";
    { re: /(\bimport\s+["'])(\.{1,2}\/[^"']+?)(["'])/g, group: 2 },
    // import("./mod")
    { re: /(\bimport\(\s*["'])(\.{1,2}\/[^"']+?)(["']\s*\))/g, group: 2 },
  ];

  for (const { re } of patterns) {
    changed = changed.replace(re, (match, p1, spec, p3) => {
      if (!spec.startsWith("./") && !spec.startsWith("../")) return match;
      if (hasKnownExtension(spec)) return match;
      if (spec.endsWith("/")) return match;

      // If the target exists with .js, add it.
      const baseDir = path.dirname(filePath);
      const candidate = path.resolve(baseDir, `${spec}.js`);
      if (isFile(candidate)) return `${p1}${spec}.js${p3}`;

      // If index.js exists, add trailing /index.js
      const candidateIndex = path.resolve(baseDir, spec, "index.js");
      if (isFile(candidateIndex)) return `${p1}${spec}/index.js${p3}`;

      return match;
    });
  }

  if (changed !== original) fs.writeFileSync(filePath, changed, "utf8");
  return changed !== original;
}

function main() {
  const distDirArg = process.argv[2];
  if (!distDirArg) {
    console.error("Usage: node scripts/rewrite-test-imports.mjs <distDir>");
    process.exitCode = 2;
    return;
  }

  const distDir = path.resolve(process.cwd(), distDirArg);
  if (!fs.existsSync(distDir) || !fs.statSync(distDir).isDirectory()) {
    console.error(`Not a directory: ${distDir}`);
    process.exitCode = 2;
    return;
  }

  const jsFiles = walk(distDir).filter((p) => p.endsWith(".js"));
  let touched = 0;
  for (const f of jsFiles) {
    if (rewriteImportsInFile(f)) touched++;
  }

  process.stdout.write(`Rewrote imports in ${touched}/${jsFiles.length} files\n`);
}

main();
