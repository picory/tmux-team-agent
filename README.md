# tmux-team-agent

![License: MIT](https://img.shields.io/badge/License-MIT-gold?style=flat-square)

Multi-agent development orchestration with Claude Code + tmux.

## Why tmux-team-agent?

This project is for teams or solo developers who want a local multi-agent runtime on top of `tmux`.

Instead of running one long opaque Claude session, `tmux-team-agent` gives you:

- a visible `leader` session
- a background `watcher`
- specialist worker panes for implementation, review, QA, and docs
- project-local prompts and task state
- a reusable runtime that can be installed once and used across repositories

This is a `tmux` runtime. It is not a native `cmux` runtime.

## Overview

The system has two layers:

- Shared runtime in `~/.tmux-runtime`
  - installed once
  - contains the launcher, prompts, scripts, and runtime code
- Project-local configuration
  - created inside each target repository
  - defines roles, prompts, tasks, outputs, and state

Once installed, the normal workflow is:

```bash
cd /path/to/your-project
teamstart
```

`teamstart` initializes missing project files, starts a `tmux` session, opens `leader` and `watcher`, and lets the watcher scale worker panes based on queued work.

## What it does

Use this when you want:

- role-based development flow instead of a single shared prompt
- visible orchestration in terminal panes
- task persistence in local JSON files
- follow-up automation such as review, QA, and docs tasks
- a repeatable local runtime for many repositories

## Prerequisites

Required:

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
- `tmux`
- `python3`
- `bash`

Recommended:

- a configured `.claude/` directory in the target repository or home directory
- `~/.local/bin` included in your `PATH`

Platform status:

- macOS: supported
- Linux: expected to work
- Windows: not supported as a first-class runtime target

## Installation

Clone this repository and run setup once:

```bash
git clone https://github.com/picory/cmux-multi-agent.git
cd cmux-multi-agent
./setup.sh
```

What `setup.sh` does:

- installs or refreshes the shared runtime in `~/.tmux-runtime`
- links `teamstart` and `teaminit` into `~/.local/bin`
- initializes the current repository with default `.ai-*` scaffolding if needed

If `teamstart` is not found after setup, add this to your shell profile:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Usage

### 1. Start the runtime in a project

```bash
cd /path/to/your-project
teamstart
```

This will:

1. create `.ai-config.yaml` if missing
2. create `.ai-agents/` files if missing
3. create `tasks/`, `outputs/`, and `.ai-state/`
4. start a `tmux` session with `leader` and `watcher`
5. launch Claude directly in the `leader` pane when available

### 2. Talk to the leader

The `leader` pane is the main Claude conductor session. You talk to it directly, and it uses the runtime queue to orchestrate specialists.

Examples:

```text
React layout 정리
Tauri 창 제어 버그 수정
watcher polling 개선
README 설치 문서 보강
```

The leader can also use the runtime CLI explicitly:

```bash
python3 ~/.tmux-runtime/lib/runtime.py enqueue --project-dir /path/to/project --role backend-coder --text "Implement API auth flow"
python3 ~/.tmux-runtime/lib/runtime.py status --project-dir /path/to/project
```

### 3. Let the watcher manage workers

The watcher reads queued tasks, spawns matching workers, and closes idle panes after the configured TTL.

Defaults:

- `AI_WATCH_INTERVAL=5`
- `AI_IDLE_TTL_SECONDS=120`

## Runtime model

### Control roles

- `leader`
  - runs Claude directly
  - accepts user requests
  - routes work into the task queue
- `watcher`
  - monitors queued tasks and active agents
  - scales worker panes up and down

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

Successful tasks can create follow-ups automatically:

- coder task -> reviewer
- coder task -> docs-writer when docs impact is implied
- reviewer task -> qa

Worker artifacts are written to:

```text
outputs/<task-id>.md
```

## Project structure

Running `teamstart` in a new project creates:

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
~/.tmux-runtime/
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

Each role prompt lives in a file so project behavior remains explicit and versioned.

## Operational notes

- This runtime requires `tmux`.
- Task and agent state are stored as JSON files and written atomically.
- Prompt files generated during execution are stored under `.ai-state/` and are gitignored by default.
- Artifact outputs are written under `outputs/` and are gitignored by default.
- The current runtime is intended for local developer workstations.

## Quick start

```bash
git clone https://github.com/picory/cmux-multi-agent.git
cd cmux-multi-agent
./setup.sh

cd /path/to/your-project
teamstart
```

Then talk to the `leader` pane and let the watcher orchestrate worker panes in `tmux`.

## License

MIT. See [LICENSE](/Volumes/m2DATA/01-works/02_personal/cmux-multi-agent/LICENSE).
