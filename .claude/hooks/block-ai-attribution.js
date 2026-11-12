// PreToolUse hook: block AI attribution in GitHub PRs, issues and comments.
const fs = require("fs");

const PATTERN = /co-authored-by:[^\n]*(claude|anthropic)|noreply@anthropic\.com|generated (with|by) [^\n]*claude/i;

// Read a body file, translating Git Bash paths (/tmp/x, /c/x) for Windows node.
function readBody(f) {
  try {
    return fs.readFileSync(f, "utf8");
  } catch {}
  try {
    const win = require("child_process").execFileSync("cygpath", ["-w", f], { encoding: "utf8" }).trim();
    return fs.readFileSync(win, "utf8");
  } catch {}
  return "";
}

let raw = "";
process.stdin.on("data", (c) => (raw += c));
process.stdin.on("end", () => {
  let input;
  try {
    input = JSON.parse(raw);
  } catch {
    process.exit(0);
  }
  const tool = input.tool_name || "";
  const ti = input.tool_input || {};
  let text = "";

  if (tool === "Bash" || tool === "PowerShell") {
    const cmd = String(ti.command || "");
    if (!/\bgh(\.exe)?\s+(pr|issue|api|release)\b/.test(cmd)) process.exit(0);
    text = cmd;
    // Also scan files passed via --body-file / -F / --input.
    const re = /(?:--body-file|--input|-F)[\s=]+("([^"]+)"|'([^']+)'|(\S+))/g;
    let m;
    while ((m = re.exec(cmd))) {
      const f = m[2] || m[3] || m[4];
      text += "\n" + readBody(f);
    }
  } else if (/github/i.test(tool)) {
    text = JSON.stringify(ti);
  } else {
    process.exit(0);
  }

  if (PATTERN.test(text)) {
    process.stderr.write(
      "Blocked: AI attribution (Claude/Anthropic co-author, 'Generated with Claude') is not allowed in PRs, issues or comments. Remove it and retry.\n"
    );
    process.exit(2);
  }
  process.exit(0);
});
