/**
 * Harness contract verification.
 *
 * This project is developed by AI agents running under DeepSeek Harness (DSH).
 * The harness only picks up two kinds of project knowledge, and both are
 * path- and format-sensitive:
 *
 * 1. Instruction files — `AGENTS.md`, discovered per directory from the project
 *    root down to the working directory, with `AGENTS.local.md` as a private
 *    overlay. A typo in the file name means the file is silently ignored and the
 *    agent works without context.
 * 2. Skills — `.dsh/skills/<name>/SKILL.md` (or a flat `.dsh/skills/<name>.md`)
 *    with YAML frontmatter carrying a non-empty `name` and `description`. A
 *    missing field means the skill is silently ignored.
 *
 * Because both failure modes are silent, they are checked mechanically here.
 */

import { readdir, readFile, stat } from "node:fs/promises";
import { join } from "node:path";

/** Instruction files the harness loads at the project root. */
export const REQUIRED_INSTRUCTION_FILES = ["AGENTS.md", "client/AGENTS.md", "server/AGENTS.md"];

/** Fields the harness requires before it will register a skill. */
export const REQUIRED_SKILL_FIELDS = ["name", "description"];

/** Inline code spans beginning with this prefix are treated as repository paths. */
const PATH_PREFIX = "repo:";

/**
 * Parse the leading `---` YAML frontmatter block of a Markdown document.
 *
 * Supports the flat, single-line `key: value` subset used by skill files, plus
 * `>`/`|` block scalars. Nested maps and sequences are reported as unsupported
 * rather than silently misread.
 *
 * @param {string} text full Markdown document.
 * @returns {{ stated: boolean, fields: Record<string, string>, body: string, problems: string[] }}
 */
export function parseFrontmatter(text) {
  const problems = [];
  const normalised = text.replace(/^\uFEFF/, "");
  if (!normalised.startsWith("---\n") && normalised !== "---") {
    return { stated: false, fields: {}, body: normalised, problems: ["missing '---' frontmatter block"] };
  }

  const end = normalised.indexOf("\n---", 3);
  if (end === -1) {
    return { stated: true, fields: {}, body: normalised, problems: ["unterminated frontmatter block"] };
  }

  const raw = normalised.slice(4, end);
  const body = normalised.slice(normalised.indexOf("\n", end + 1) + 1);
  /** @type {Record<string, string>} */
  const fields = {};
  // Set only while a `>`/`|` block scalar is open, so an indented line that does
  // not belong to one is reported instead of being silently absorbed.
  let blockKey = null;

  for (const line of raw.split("\n")) {
    if (line.trim() === "") continue;

    if (blockKey !== null) {
      const continuation = /^\s+(.*)$/.exec(line);
      if (continuation) {
        fields[blockKey] = `${fields[blockKey]} ${continuation[1].trim()}`.trim();
        continue;
      }
      blockKey = null;
    }

    const pair = /^([A-Za-z0-9_-]+):\s*(.*)$/.exec(line);
    if (!pair) {
      problems.push(`unsupported frontmatter line: ${line.trim()}`);
      continue;
    }
    const [, key, rawValue] = pair;
    let value = rawValue.trim();
    if (value === ">" || value === "|") {
      fields[key] = "";
      blockKey = key;
      continue;
    }
    if (
      (value.startsWith('"') && value.endsWith('"') && value.length > 1) ||
      (value.startsWith("'") && value.endsWith("'") && value.length > 1)
    ) {
      value = value.slice(1, -1);
    }
    fields[key] = value;
  }

  return { stated: true, fields, body, problems };
}

/**
 * Extract `repo:`-prefixed inline code spans from a Markdown body. Skill packs
 * use these to point at the authoritative files, so a stale reference is caught
 * instead of misleading the next agent.
 * @param {string} body Markdown body.
 * @returns {string[]} repository-relative paths.
 */
export function extractRepoPaths(body) {
  const paths = new Set();
  for (const match of body.matchAll(/`([^`\n]+)`/g)) {
    const span = match[1].trim();
    if (!span.startsWith(PATH_PREFIX)) continue;
    paths.add(span.slice(PATH_PREFIX.length).trim());
  }
  return [...paths].sort();
}

/** @param {string} path @returns {Promise<boolean>} */
async function exists(path) {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
}

/**
 * Verify the instruction-file hierarchy and every project skill.
 * @param {string} root repository root.
 * @returns {Promise<{ ok: boolean, skillCount: number, problems: string[], notes: string[] }>}
 */
export async function checkHarness(root) {
  const problems = [];
  const notes = [];

  for (const relativePath of REQUIRED_INSTRUCTION_FILES) {
    const absolute = join(root, relativePath);
    if (!(await exists(absolute))) {
      problems.push(`missing instruction file: ${relativePath}`);
      continue;
    }
    const text = await readFile(absolute, "utf8");
    if (text.trim().length < 200) {
      problems.push(`instruction file is too thin to guide an agent: ${relativePath}`);
    }
  }

  const skillsRoot = join(root, ".dsh/skills");
  if (!(await exists(skillsRoot))) {
    problems.push("missing project skill root: .dsh/skills");
    return { ok: problems.length === 0, skillCount: 0, problems, notes };
  }

  const entries = await readdir(skillsRoot, { withFileTypes: true });
  const skillFiles = [];
  for (const entry of entries) {
    if (entry.isDirectory()) {
      skillFiles.push(join(skillsRoot, entry.name, "SKILL.md"));
    } else if (entry.isFile() && entry.name.endsWith(".md")) {
      // The provider treats a flat `.md` directly under the skills root as a
      // skill candidate, so a plain README here is a silent trap: it would be
      // scanned, found to have no frontmatter, and ignored. Reject it.
      problems.push(
        `flat file in the skill root is treated as a skill candidate and must be moved out: .dsh/skills/${entry.name}`,
      );
    } else if (!entry.name.startsWith(".")) {
      problems.push(`unexpected entry in .dsh/skills: ${entry.name}`);
    }
  }

  if (skillFiles.length === 0) problems.push("no skills found under .dsh/skills");

  /** @type {Map<string, string>} */
  const seenNames = new Map();
  for (const file of skillFiles) {
    const display = file.slice(root.length + 1).split("\\").join("/");
    if (!(await exists(file))) {
      problems.push(`skill directory without SKILL.md: ${display}`);
      continue;
    }

    const text = await readFile(file, "utf8");
    const { stated, fields, body, problems: parseProblems } = parseFrontmatter(text);
    if (!stated) problems.push(`${display}: ${parseProblems.join("; ")}`);
    for (const problem of parseProblems) problems.push(`${display}: ${problem}`);

    for (const field of REQUIRED_SKILL_FIELDS) {
      const value = fields[field];
      if (value === undefined || value.length === 0) {
        problems.push(`${display}: frontmatter is missing a non-empty '${field}'`);
      }
    }

    const declared = fields.name;
    if (declared !== undefined) {
      // Every candidate is `<skills>/<name>/SKILL.md`; the directory name is the
      // name the provider will register, so frontmatter must agree with it.
      const expected = file.slice(skillsRoot.length + 1).split(/[\\/]/)[0];
      if (declared !== expected) {
        problems.push(`${display}: frontmatter name '${declared}' does not match directory '${expected}'`);
      }
      const previous = seenNames.get(declared);
      if (previous !== undefined) problems.push(`${display}: duplicate skill name '${declared}' also in ${previous}`);
      else seenNames.set(declared, display);
    }

    const description = fields.description ?? "";
    if (description.length > 0 && description.length < 20) {
      problems.push(`${display}: description is too short to let an agent decide when to load it`);
    }
    if (body.trim().length < 200) problems.push(`${display}: body is too thin to be useful`);

    for (const path of extractRepoPaths(body)) {
      if (!(await exists(join(root, path)))) problems.push(`${display}: references '${path}', which does not exist`);
    }
  }

  notes.push(`instruction files: ${REQUIRED_INSTRUCTION_FILES.length}`);
  notes.push(`project skills: ${skillFiles.length}`);
  return { ok: problems.length === 0, skillCount: skillFiles.length, problems, notes };
}
