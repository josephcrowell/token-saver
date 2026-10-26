# Token-Saver Plugin

Token-saver automatically compresses verbose tool output to save tokens.

## How it works
- A PostToolUse hook compresses output after Bash, Read, Grep, Glob, Agent, and WebFetch
  calls finish (the same model as the Kilo Code plugin). Commands run unmodified and once,
  under Claude Code's normal permission rules.
- Output is routed through specialized compression processors (git, docker, npm, cmake,
  Qt, terraform, kubectl, etc.). Source code and config files read with Read are never
  compressed, and ranged reads (offset/limit) are left untouched.
- `graphify query "<question>"` Bash calls are measured automatically and reported as
  Graphify savings in the session stats.

## Important rules
- Never wrap `token-saver` CLI commands themselves (avoid infinite loops)
- Shell commands with redirections (>), complex pipes, sudo, or interactive programs are
  never compressed
- Debug mode: set TOKEN_SAVER_DEBUG=true environment variable
