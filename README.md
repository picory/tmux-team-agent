# cmux-multi-agent

![License: MIT](https://img.shields.io/badge/License-MIT-gold?style=flat-square)

Multi-agent development orchestration with Claude Code + cmux.

## Why cmux-multi-agent?

Claude Code can already coordinate work, but visible multi-agent execution is still useful when you want:

- role-based parallel work instead of one long opaque session
- a persistent `leader` and `watcher` control plane
- project-local agent prompts and policy
- auto-scaling worker windows based on queued work
- a repeatable runtime you can drop into multiple repositories

`cmux-multi-agent` puts a runtime layer on top of `cmux` or `tmux` so that agent orchestration becomes a project capability, not a one-off terminal trick.

## Overview

This repository provides two layers:

- Shared runtime in `~/.ai-runtime`
  - installed once
  - contains the reusable launcher, watcher, prompts, and helper scripts
- Project-local configuration
  - created inside each target repository
  - defines agent roles, prompts, tasks, outputs, and state

Once installed, the expected workflow is:

```bash
cd /path/to/your-project
ai-start
```

`ai-start` ensures project scaffolding exists, starts a mux session, opens `leader` and `watcher`, and lets the watcher spawn specialist workers as tasks appear.
The `leader` window is an interactive Claude conductor session, not a custom text prompt loop.

## Why use it?

Use this when you want a local multi-agent development runtime with explicit orchestration.

- You want specialist roles such as `backend-coder`, `frontend-coder`, `desktop-coder`, `crawler-coder`, `reviewer`, `qa`, and `docs-writer`.
- You want to watch parallel work happen in visible panes instead of waiting for one final summary.
- You want project prompts and role rules to live in versioned files.
- You want task state, artifacts, and follow-up actions like review and QA to be persisted locally.
- You want one runtime that can be reused across many repositories.

## Prerequisites

You need the following installed on the machine:

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
- `cmux` or `tmux`
  - `cmux` is preferred only when it supports tmux-compatible session commands
  - otherwise the runtime falls back to `tmux` automatically
- `python3`
- `bash`

Recommended:

- a configured `.claude/` directory in the target project or home directory
- `~/.local/bin` available in your `PATH`

Current platform support:

- macOS: supported
- Linux: expected to work with the same shell and mux assumptions
- Windows: not yet supported as a first-class runtime target

## Installation

Clone this repository and run setup once:

```bash
git clone https://github.com/picory/cmux-multi-agent.git
cd cmux-multi-agent
./setup.sh
```

What `setup.sh` does:

- installs or refreshes the shared runtime in `~/.ai-runtime`
- links `ai-start` and `ai-init` into `~/.local/bin`
- initializes the current repository with default `.ai-*` scaffolding if it does not already exist

If `ai-start` is not found after setup, add this to your shell profile:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Usage

### 1. Start a project runtime

Move into the repository where you want multi-agent execution and run:

```bash
cd /path/to/your-project
ai-start
```

This will:

1. create `.ai-config.yaml` if missing
2. create `.ai-agents/` role prompt files if missing
3. create `tasks/`, `outputs/`, and `.ai-state/`
4. open a mux session with `leader` and `watcher`
5. start Claude directly inside the `leader` window

### 2. Talk to Claude in the leader window

The leader window is the main Claude session. You talk to it directly, and it uses the runtime queue to orchestrate specialists.

Examples:

```text
React layout 정리
```

```text
Tauri 창 제어 버그 수정
```

```text
watcher polling 개선
```

You can also target roles explicitly:

```text
/spawn backend-coder API 인증 흐름 정리
/review 회귀 위험 점검
/qa watcher 동작 검증
/docs README 설치 문서 보강
/status
```

Under the hood, the leader uses runtime commands such as:

```bash
python3 ~/.ai-runtime/lib/runtime.py enqueue --project-dir /path/to/project --role backend-coder --text "Implement API auth flow"
python3 ~/.ai-runtime/lib/runtime.py status --project-dir /path/to/project
```

### 3. Watch execution

The watcher reads queued tasks, scales up matching worker roles, and closes idle worker windows after the configured TTL.

Defaults:

- `AI_WATCH_INTERVAL=5`
- `AI_IDLE_TTL_SECONDS=120`

## Runtime model

### Control roles

- `leader`
  - runs Claude directly
  - accepts work from the user
  - routes tasks through the runtime queue
  - acts as the orchestration entry point
- `watcher`
  - monitors task queue and agent pool
  - scales workers up and down

### Specialist roles

- `backend-coder`
- `frontend-coder`
- `desktop-coder`
- `crawler-coder`
- `reviewer`
- `qa`
- `docs-writer`

### Task lifecycle

Tasks are stored in `tasks/tasks.json` and include metadata such as:

- role
- status
- priority
- scope
- dependencies
- follow-ups
- artifacts
- result

Successful tasks can generate follow-ups automatically:

- coder task -> reviewer
- coder task -> docs-writer when docs impact is implied
- reviewer task -> qa

Worker results are written to:

```text
outputs/<task-id>.md
```

## Project structure

Running `ai-start` in a new project creates:

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

Shared runtime files live in:

```text
~/.ai-runtime/
├─ bin/
├─ scripts/
├─ prompts/
├─ templates/
└─ lib/
```

## Configuration

The project runtime is controlled by `.ai-config.yaml`.

Example:

```yaml
project: my-project

agents:
  - name: leader
    prompt: .ai-agents/leader.md

  - name: backend-coder
    prompt: .ai-agents/backend-coder.md
    scale: auto
    min: 0
    max: 3

  - name: reviewer
    prompt: .ai-agents/reviewer.md
    scale: auto
    min: 0
    max: 2

paths:
  tasks: ./tasks
  outputs: ./outputs
```

Each role prompt lives in a file so that project behavior stays explicit and versioned.

## Operational notes

- `cmux` is preferred, `tmux` is used automatically if `cmux` is missing.
- Some `cmux` builds use a workspace/window CLI instead of tmux-compatible `new-session` commands. In that case this runtime falls back to `tmux`.
- Task and agent state are stored as JSON files and written atomically.
- Prompt files generated during execution are stored under `.ai-state/` and are gitignored by default.
- Artifact outputs are written under `outputs/` and are gitignored by default.
- The current runtime is designed for local developer workstations, not multi-user remote scheduling.

## Quick start summary

```bash
git clone https://github.com/picory/cmux-multi-agent.git
cd cmux-multi-agent
./setup.sh

cd /path/to/your-project
ai-start
```

Then submit work in the `leader` window and let the watcher handle worker orchestration.

## License

MIT. See [LICENSE](/Volumes/m2DATA/01-works/02_personal/cmux-multi-agent/LICENSE).
