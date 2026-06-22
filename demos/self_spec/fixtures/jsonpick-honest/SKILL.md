---
name: jsonpick-honest
description: Pick a top-level value out of a JSON object by key.
metadata: {"openclaw":{"requires":{"bins":["python3"]}}}
---

# jsonpick-honest

A tiny example skill that ships a *checkable* usage example: a command AND the
output it produces. That input/output pair is the author's own committed spec.

## Usage

```sh
$ echo '{"version": "1.2", "name": "demo"}' | python scripts/pick.py .version
1.2
$ echo '{"items": [1, 2, 3]}' | python scripts/pick.py .items
[1, 2, 3]
```
