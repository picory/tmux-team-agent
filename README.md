# cmux-multi-agent

![License: MIT](https://img.shields.io/badge/License-MIT-gold?style=flat-square)

Multi-agent development orchestration with Claude Code + cmux.

`ai-start` installs or refreshes the shared runtime in `~/.ai-runtime`, initializes the current project, and starts a multi-agent mux session with a `leader` window and a `watcher` window.

## What this repository provides

- Shared runtime installer
- Project scaffolding for `.ai-config.yaml` and `.ai-agents/*.md`
- Interactive `leader` loop for submitting work
- `watcher` loop that reads queued tasks and auto-spawns agent windows
- `spawn.sh` and `kill.sh` wrappers for runtime control
- CommentMate-style specialist roles for backend, frontend, desktop, crawler, QA, docs, and review
- Rich task records with policy, followups, artifacts, and result metadata

## First run

```bash
cd /path/to/project
/path/to/this/repo/setup.sh
ai-start
```

`setup.sh` installs or refreshes the shared runtime and initializes the current project if it has not been configured yet.

## Project structure

```text
project/
├─ .ai-config.yaml
├─ .ai-agents/
│  ├─ leader.md
│  ├─ backend-coder.md
│  ├─ frontend-coder.md
│  ├─ desktop-coder.md
│  ├─ crawler-coder.md
│  ├─ reviewer.md
│  ├─ qa.md
│  └─ docs-writer.md
├─ .ai-state/
│  └─ agent_pool.json
├─ tasks/
│  └─ tasks.json
└─ outputs/
```

## Notes

- The runtime prefers `cmux` when available and falls back to `tmux` if `cmux` is not installed.
- Claude CLI is used for spawned workers when available. If it is missing, worker windows print the prepared prompt and exit.
- The leader window auto-routes plain text by keywords. UI and React work go to `frontend-coder`, Tauri and mux work go to `desktop-coder`, watcher and automation work go to `crawler-coder`, docs go to `docs-writer`, and unmatched work falls back to `backend-coder`.
- Use `/spawn <role> <text>` to target a specialist explicitly, `/qa <text>` for validation, `/docs <text>` for docs, `/review <text>` for review, and `/status` to inspect state.
- Idle auto-scaled windows are cleaned up by the watcher after `AI_IDLE_TTL_SECONDS` seconds. Default is `120`.
- Completed worker runs write `outputs/<task-id>.md` and store the artifact path in task state.
- Successful coder tasks can enqueue reviewer, QA, and docs follow-ups based on per-task policy.

## License

MIT. See [LICENSE](/Volumes/m2DATA/01-works/02_personal/cmux-multi-agent/LICENSE).
