---
description: "Show token-saver compression statistics and savings"
---

Run the token-saver stats command to display savings:

```bash
token-saver stats
```

If the `token-saver` CLI is not in PATH, use:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/src/cli.py" stats
```

Present a summary of tokens saved in the current session and overall.
Include both directly measured command-output compression and the separately
labeled estimated Graphify context savings when Graphify queries were recorded.
