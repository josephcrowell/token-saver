# Autotools Processor

Compresses output from autotools, autoconf, automake, libtoolize, and
`./configure`.

## What it compresses

- Routine `checking for X... yes` and `checking for X... no` lines
- Tool trace messages: `autoreconf: entering directory`,
  `autoreconf: running: aclocal`, `autoreconf: leaving directory`
- Verbose "creating …" line noise

## What it preserves

- `checking for X... no` for X that looks like a dependency (not a trait)
- `checking for X... cached` markers
- Error blocks with their indented continuations
- Warnings
- `configure: creating ./config.status` (result marker)

## Trait vs. dependency detection

The processor suppresses "no" results for trait-style checks such as
`checking whether we are cross compiling... no` while still flagging
`checking for libxml-2.0... no`. This avoids flooding the model with
benign `no` answers.
