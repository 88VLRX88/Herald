# Herald Mode Files

Herald now loads modes in one style: every runtime mode is a `.md` or `.txt`
document from `agent.mode_dirs`.

By default the config points to one directory:

```json
"agent": {
  "mode": "coder",
  "mode_dirs": [".Herald/modes"]
}
```

On startup Herald creates the default mode files there if they are missing:

- `.Herald/modes/coder.md`
- `.Herald/modes/philosopher.md`
- `.Herald/modes/mathematician.md`
- `.Herald/modes/research.md`
- `.Herald/modes/assist.md`

After that, defaults and your own modes are loaded the same way: as mode files.
Only one mode is active at a time, and only that selected mode is injected into
the system prompt.

## Creating A Mode

Create a file such as `.Herald/modes/reviewer.md`:

```markdown
---
id: code-reviewer
label: Code Reviewer
aliases: reviewer, review, ревьюер
description: Finds bugs, regressions, security risks, and missing tests in code changes.
---

Act as a strict code reviewer. Prioritize correctness and risk over style.
Lead with findings ordered by severity. Include concrete file and line references.
Mention test gaps and residual risk.
```

Use it from chat:

```text
/mode code-reviewer
/mode ревьюер
```

Or from CLI:

```bash
python cli_agent.py --mode code-reviewer "review the current project"
```

## Selection

Herald selects exactly one mode:

1. Try exact `id`.
2. Try exact `alias` or `label`.
3. If there is no exact match, run lightweight retrieval over every loaded mode
   file's `id`, `label`, `aliases`, `description`, and instruction body.

For example, `/mode security review` can resolve to `code-reviewer` if that
document is the best match.

## Metadata Fields

- `id`: stable mode id. Defaults to the file name without extension.
- `label`: display name. Defaults to the first Markdown heading or the id.
- `aliases`: comma-separated aliases or YAML-style list.
- `description`: retrieval text for fuzzy selection.

Do not reuse ids or aliases across files. If two mode files claim the same id or
alias, Herald reports an error instead of guessing.
