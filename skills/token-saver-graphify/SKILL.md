---
name: token-saver-graphify
description: Use Graphify before exploring or explaining a codebase, architecture, implementation flow, or file relationships. Prefer an existing graphify-out graph, query it for focused context, and update it after code changes so Kilo sends less repository content to the model.
compatibility: Requires the graphify command for graph creation and updates. Existing graphify-out/graph.json files can be queried locally.
---

# Token-Saver + Graphify

Use Graphify as a repository-context compression layer alongside Token-Saver's
terminal-output compression.

## Codebase questions

Before broad file searches or reading many source files:

1. Check for `graphify-out/graph.json` in the workspace root.
2. If it exists, run `graphify query "<the user's question>"` first.
3. Use the returned nodes, relationships, and `source_location` values to narrow
   subsequent reads to the smallest relevant set of files.
4. Never claim a relationship that is absent from the graph or source code.

If no graph exists, tell the user that the project needs an initial graph and run
`graphify .` when installation and permissions allow it. Graphify's structural
code extraction is local and does not require an LLM. Semantic extraction for
documents may use Gemini only when the user has configured its API key.

## After code changes

After modifying code files, run:

```bash
graphify update .
```

Do not rebuild after every individual edit; update once after the change set is
complete. For doc, paper, or image changes, use the full Graphify update workflow
because the lightweight code update only performs structural extraction.

## Token behavior

- Token-Saver compresses verbose Bash output after Kilo executes commands.
- Graphify reduces how much repository content needs to be searched and read.
- Graphify structural extraction is deterministic and local.
- Neither integration should silently route work through Kilo's free model router.
