---
status: superseded
closed: 2026-10-26
---
# Offload · WIKI — hito gwork (parked: create issue when gh works)

## Owner command (signed body ready)

Run from any cwd with `gh` auth:

```bash
export SECRETARY_SKILL=wind-down
export SECRETARY_BRANCH=main
SIG_MARK=$(~/.claude/scripts/sec-signature.sh wind-down --mark)
SIG_FOOT=$(~/.claude/scripts/sec-signature.sh wind-down --footer)
gh issue create --repo alvaroemur/cowork-secretary \
  --title "wiki: consolidar hito gwork (rename + multi-file + submodule core)" \
  --label "hilo:wiki" \
  --body "${SIG_MARK}

## Triage
WIKI — durable knowledge

## Qué consolidar (2026-09-23)
1. Rename cowork-drivesync → gwork (alvaroemur/gwork); local path may remain ~/Dev/cowork-drivesync.
2. Multi-file: gwork PR #13 @ 503d476 — manifest v2, item add / organize.
3. secretary-core plugins/gwork + secretary gwork (PRs #55, #56 pin 503d476).
4. Skills ~/.claude/skills/gwork/ (+ aliases); AGENTS.md via gwork #14.

## Destino
wiki-write → knowledge/wiki/articulos/ (temas/gwork o modulos/gwork). source wind-down.

## Prompt
Consolida a wiki el hito gwork 2026-09-23. cwd ~/.secretary. No reauth gog. No código.

---
${SIG_FOOT}"
```

## Paste-ready restart (after issue exists)

```
Consolida a wiki el hito gwork 2026-09-23 (rename, multi-file #13, submodule core #55/#56, skills, AGENTS #14). Usa wiki-write; source wind-down. Repo cwd: ~/.secretary. No ejecutes código ni reauth.
```
