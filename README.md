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
- structured workflow pipelines that enforce task ordering via `depends_on`

This is a `tmux` runtime for local multi-agent development orchestration.

## Overview

The system has two layers:

- Shared runtime in `~/.tmux-runtime`
  - installed once
  - contains the launcher, prompts, scripts, runtime code, and workflow definitions
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
- structured pipelines that enforce ordering between stages
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

Optional:

- `codex` CLI — enables the Codex workflow pipeline (automatic Codex review gates)

Platform status:

- macOS: supported
- Linux: expected to work
- Windows: not supported as a first-class runtime target

If you are on Windows, use WSL2 with `tmux`, `python3`, `bash`, and Claude Code installed inside WSL, and run the runtime from the WSL project path.

## Installation

Clone this repository and run setup once:

```bash
git clone https://github.com/picory/tmux-team-agent.git
cd tmux-team-agent
./setup.sh
```

If you are on Windows, run these steps inside WSL2 rather than native PowerShell or CMD.

What `setup.sh` does:

- installs or refreshes the shared runtime in `~/.tmux-runtime`
- links `teamstart`, `teaminit`, `teamclean`, `teamupdate` into `~/.local/bin`
- initializes the current repository with default `.ai-*` scaffolding if needed
- installs Claude Code skills (`reflect`, `blueprint`, `deep-dive`) into `~/.claude/skills/`

If `teamstart` is not found after setup, add this to your shell profile:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Usage

### 0. Clean a previous install before reinstalling

```bash
cd /path/to/your-project
teamclean
```

`teamclean` stops the project tmux session, removes the shared runtime install, and clears the project-local `.ai-state/`, `tasks/`, and `outputs/` directories so `./setup.sh` can start from a clean slate.

### 1. Start the runtime in a project

```bash
cd /path/to/your-project
teamstart
```

First run triggers an interactive wizard that:

1. runs `doctor` to check the environment
2. creates `.claude/settings.json` if missing
3. adds `CLAUDE.md` with team conventions
4. installs Claude Code skills
5. prompts for any `.env` or config values

Subsequent runs skip the wizard and start immediately.

### 2. Talk to the leader

The `leader` pane is the main Claude conductor session. You talk to it directly, and it uses the runtime queue to orchestrate specialists.

**Ad-hoc tasks:**

```text
React layout 정리
Tauri 창 제어 버그 수정
watcher polling 개선
README 설치 문서 보강
```

**Leader slash commands:**

```text
/review <text>                   reviewer task
/qa <text>                       qa task
/docs <text>                     docs-writer task
/spawn <role> [text]             enqueue for a specific role
/workflow standard <description> launch the standard pipeline
/workflow codex <description>    launch the Codex-gated pipeline
/lesson [role] | <title> | <detail>  record a lesson
/lessons [role]                  list lessons
/status                          show queue and agent state
```

**Leader CLI (from any terminal):**

```bash
python3 ~/.tmux-runtime/lib/runtime.py enqueue \
  --project-dir /path/to/project \
  --role backend-coder \
  --text "Implement API auth flow"

python3 ~/.tmux-runtime/lib/runtime.py workflow \
  --project-dir /path/to/project \
  --name standard \
  --task "로그인 기능 구현"

python3 ~/.tmux-runtime/lib/runtime.py status \
  --project-dir /path/to/project
```

### 3. Let the watcher manage workers

The watcher reads queued tasks, spawns matching workers, and closes idle panes after the configured TTL.

Defaults:

- `AI_WATCH_INTERVAL=5`
- `AI_IDLE_TTL_SECONDS=120`

## Workflow Pipelines

`/workflow` enqueues a full multi-stage pipeline as a sequence of tasks. Each stage is created with `depends_on` pointing to its predecessor, so workers only pick up a stage after the prior one completes.

### Standard workflow (without Codex)

```
/workflow standard <task description>
```

| # | Stage | Role |
|---|---|---|
| 1 | 요구사항 분석 및 PRD 작성 | product-manager |
| 2 | UX 설계 및 화면 기획 | ux-designer |
| 3 | 기술 아키텍처 설계 및 개발 계획 | architect |
| 4 | 기능 구현 | backend-coder |
| 5 | 코드 리뷰 | reviewer |
| 6 | 테스트 시나리오 및 하네스 설계 | test-harness-engineer |
| 7 | 테스트 실행 및 결과 검증 | qa |
| 8 | 보완/고도화 | backend-coder |
| 9 | 성능 점검 및 최적화 | performance-engineer |
| 10 | 최종 QA 검증 | qa |
| 11 | 보안 취약점 점검 | security-engineer |
| 12 | 배포 환경 준비 및 인프라 확인 | devops-engineer |
| 13 | 작업 완료 보고서 작성 | product-manager |

### Codex workflow (with Codex CLI)

```
/workflow codex <task description>
```

| # | Stage | Role |
|---|---|---|
| 1 | 기술 아키텍처 설계 및 개발 계획 | architect |
| 2 | **[Codex]** 개발 계획 검수 (오버스펙/보완/추가) | test-harness-engineer |
| 3 | 기능 구현 | backend-coder |
| 4 | 코드 리뷰 | reviewer |
| 5 | 테스트 시나리오 및 하네스 설계 | test-harness-engineer |
| 6 | **[Codex]** 테스트 시나리오 검수 | test-harness-engineer |
| 7 | 테스트 실행 | qa |
| 8 | **[Codex]** 테스트 결과 검수 | test-harness-engineer |
| 9 | 보완/고도화 | backend-coder |
| 10 | 보안 취약점 점검 | security-engineer |
| 11 | **[Codex]** 최종 검수 진행 | test-harness-engineer |
| 12 | Codex 검수 완료 보고서 작성 | product-manager |

Codex stages are assigned to `test-harness-engineer` with `metadata.uses_codex = true`. The Codex workflow is designed for use when the `codex` CLI is available (`teamstart doctor` reports its status).

### How `depends_on` enforcement works

`claim_task()` only marks a task as `running` when all tasks listed in its `depends_on` are in a completed state (`done`, `reviewed`, or `failed`). This means:

- the watcher will not spawn a worker for stage N until stage N-1 is finished
- stages can be claimed out of order only if their dependencies are met
- a failed dependency does not block downstream stages (it counts as completed)

## CLI reference

### teamstart

```
teamstart [project-dir]
teamstart wizard [project-dir]
teamstart update
teamstart doctor [project-dir]
teamstart help
teamstart lesson --title TEXT --detail TEXT [--role ROLE]
teamstart lessons [--role ROLE]
```

| Argument / subcommand | Description |
|---|---|
| `project-dir` | Path to the target project (default: `$PWD`) |
| `wizard [project-dir]` | Run the first-run setup wizard manually |
| `update` | Pull latest from GitHub and refresh `~/.tmux-runtime` |
| `doctor [project-dir]` | Check environment and project configuration |
| `help` | Show usage and available options |
| `lesson` | Record a lesson learned (see Lessons section) |
| `lessons` | List recorded lessons |

| Environment variable | Default | Description |
|---|---|---|
| `TMUX_RUNTIME_HOME` | `~/.tmux-runtime` | Override the shared runtime location |
| `TMUX_BIN` | `tmux` | Use a custom tmux binary |
| `AI_WATCH_INTERVAL` | `5` | Watcher polling interval in seconds |
| `AI_IDLE_TTL_SECONDS` | `120` | Seconds before an idle worker pane is closed |

**teamstart doctor** checks:

- Required binaries: `tmux`, `python3`, `claude`
- Optional binaries: `codex` (reports available/not found without failing)
- Shared runtime install (`~/.tmux-runtime` structure)
- `teamstart` / `teaminit` / `teamclean` / `teamupdate` symlinks in `~/.local/bin`
- `~/.local/bin` presence in `$PATH`
- Active environment variable values
- Project scaffolding (`.ai-config.yaml`, `.ai-agents/`, `tasks/`, `outputs/`, `.ai-state/`)

### teamupdate

```
teamupdate
```

Same as `teamstart update`. Pulls latest changes from GitHub and refreshes `~/.tmux-runtime`. Run from any directory.

### teaminit

```
teaminit [project-dir]
```

Initializes project scaffolding without starting the tmux session.

| Argument | Description |
|---|---|
| `project-dir` | Path to the target project (default: `$PWD`) |

### teamclean

```
teamclean [project-dir]
```

Stops the tmux session and clears runtime state for a clean reinstall.

| Argument | Description |
|---|---|
| `project-dir` | Path to the target project (default: `$PWD`) |

### runtime.py (advanced)

The underlying Python CLI used by all wrapper commands. Available subcommands:

```bash
python3 ~/.tmux-runtime/lib/runtime.py <subcommand> [options]
```

| Subcommand | Description |
|---|---|
| `start` | Start the tmux session for a project |
| `init` | Initialize project scaffolding only |
| `clean` | Stop session and remove runtime state |
| `enqueue` | Push a single task into the queue |
| `workflow` | Enqueue a full pipeline workflow |
| `status` | Print current queue and agent status |
| `spawn` | Manually spawn a worker pane |
| `kill` | Kill a named worker pane |
| `update` | Pull latest changes and refresh the runtime |
| `doctor` | Check environment and project configuration |
| `wizard` | Run the first-run setup wizard |
| `lesson` | Record a lesson learned |
| `lessons` | List recorded lessons |
| `help` | Show usage summary |
| `watch` | Run the watcher loop (used internally) |
| `leader-loop` | Run the leader loop (used internally) |
| `run-agent` | Run an agent in the current pane (used internally) |

**enqueue options:**

```
--project-dir PATH   (required) project root
--role ROLE          (required) target role (e.g. backend-coder, reviewer)
--text TEXT          (required) task description
--created-by NAME    who queued this task (default: leader)
--priority LEVEL     normal | high (default: normal)
--scope SCOPE        task scope label (default: task)
```

**workflow options:**

```
--project-dir PATH   (required) project root
--name NAME          (required) workflow name: standard | codex
--task TEXT          (required) task description used in all stage titles
```

**spawn options:**

```
--project-dir PATH   (required) project root
--role ROLE          (required) target role
--agent-name NAME    assign a specific agent name
--task-id ID         associate with an existing task
```

**kill options:**

```
--project-dir PATH   (required) project root
--agent-name NAME    (required) name of the agent pane to close
```

**lesson options:**

```
--project-dir PATH   (required) project root
--title TEXT         (required) short summary of the mistake
--detail TEXT        (required) what went wrong and how to avoid it
--role ROLE          target role (omit to apply to all roles)
--task-id ID         link to the source task
```

**lessons options:**

```
--project-dir PATH   (required) project root
--role ROLE          filter by role (omit for all)
```

## Lessons

Agents and the leader can record mistakes to prevent recurrence. Each lesson is saved to two places:

- **`.ai-state/lessons.json`** — injected into the agent's system prompt on the next run
- **`~/.claude/projects/<project>/memory/`** — Claude Code memory, persisted across sessions as `feedback` type

### Record a lesson

From the leader pane:
```text
/lesson backend-coder | Always check pool size before deploy | Deploying without DB_POOL_SIZE caused connection exhaustion under load.
/lesson | Never hardcode env values | Use env vars in all configs — hardcoded values caused prod/staging mismatch.
```

From any terminal:
```bash
python3 ~/.tmux-runtime/lib/runtime.py lesson \
  --project-dir /path/to/project \
  --role backend-coder \
  --title "Always check pool size before deploy" \
  --detail "Deploying without DB_POOL_SIZE caused connection exhaustion under load."
```

### List lessons

```bash
teamstart lessons                        # all lessons
teamstart lessons --role backend-coder   # filtered by role
python3 ~/.tmux-runtime/lib/runtime.py lessons --project-dir /path/to/project
```

### How injection works

When a worker agent starts, `merge_prompt()` reads `.ai-state/lessons.json`, filters lessons matching the agent's role (plus global lessons with no role), and appends a `## Lessons learned` section to the system prompt. The agent sees the lessons before any task context.

## Runtime model

### Control roles

- `leader`
  - runs Claude directly
  - accepts user requests
  - routes work into the task queue
  - handles `/workflow` commands to enqueue pipelines
- `watcher`
  - monitors queued tasks and active agents
  - scales worker panes up and down
  - respects `depends_on` ordering (only spawns tasks whose dependencies are complete)

### Specialist roles

**Core developers:**
- `backend-coder`
- `frontend-coder`
- `desktop-coder`
- `crawler-coder`
- `mobile-coder`
- `embedded-coder`
- `ai-ml-engineer`

**Quality & review:**
- `reviewer`
- `qa`
- `test-harness-engineer`
- `performance-engineer`
- `security-engineer`

**Architecture & infrastructure:**
- `architect`
- `devops-engineer`
- `cloud-architect`
- `network-engineer`
- `dba`

**Product & design:**
- `product-manager`
- `ux-designer`

**Documentation:**
- `docs-writer`

### Task lifecycle

Tasks are stored in `tasks/tasks.json` and include metadata such as:

- role
- status (`pending` → `running` → `done` / `reviewed` / `failed`)
- priority
- scope
- `depends_on` — list of task IDs that must complete before this task can start
- follow-ups
- artifacts
- result

**Automatic follow-up tasks:**

- coder task `done` → reviewer (when `auto_review: true`)
- coder task `done` → docs-writer (when `auto_docs: true` and task description implies docs)
- reviewer task `reviewed` → qa (when `auto_qa: true`)

**Workflow pipelines** create all stages upfront with `depends_on` chains instead of using auto-follow-ups.

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
│  ├─ mobile-coder.md
│  ├─ embedded-coder.md
│  ├─ ai-ml-engineer.md
│  ├─ reviewer.md
│  ├─ qa.md
│  ├─ test-harness-engineer.md
│  ├─ performance-engineer.md
│  ├─ security-engineer.md
│  ├─ architect.md
│  ├─ devops-engineer.md
│  ├─ cloud-architect.md
│  ├─ network-engineer.md
│  ├─ dba.md
│  ├─ product-manager.md
│  ├─ ux-designer.md
│  └─ docs-writer.md
├─ .ai-state/
│  ├─ agent_pool.json
│  └─ lessons.json
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
├─ workflows/
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

  - name: test-harness-engineer
    prompt: .ai-agents/test-harness-engineer.md
    scale: auto
    min: 0
    max: 1

  - name: security-engineer
    prompt: .ai-agents/security-engineer.md
    scale: auto
    min: 0
    max: 1

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

## Updating

```bash
teamupdate
# or equivalently:
teamstart update
```

`teamupdate` does two things in sequence:

1. `git pull` in the original clone directory (auto-detected via symlink)
2. Re-runs setup to refresh `prompts/`, `templates/`, `skills/`, and `workflows/` in `~/.tmux-runtime`

No arguments needed. Run it from any directory.

### What gets symlinked vs copied

`setup.sh` installs the runtime in two ways:

| Path in `~/.tmux-runtime` | Install type | Effect of repo change |
|---|---|---|
| `bin/team*` | symlink | **immediate** — no update needed |
| `scripts/*.sh` | symlink | **immediate** |
| `lib/runtime.py` | symlink | **immediate** |
| `prompts/*.base.md` | **copy** | `teamupdate` required |
| `templates/` | **copy** | `teamupdate` required |
| `skills/` | **copy** | `teamupdate` required |
| `workflows/*.json` | **copy** | `teamupdate` required |

Project files in `.ai-agents/*.md` are created only when they do not exist — update never overwrites them.

### Applying updated base prompts to an existing project

`teamupdate` does not overwrite existing `.ai-agents/*.md` files. Because base and project prompts are concatenated at runtime, most base prompt additions apply automatically. For larger changes:

```bash
# drop the project override to fall back to the updated base
rm /path/to/project/.ai-agents/<role>.md

# or inspect the diff and merge manually
diff ~/.tmux-runtime/prompts/<role>.base.md /path/to/project/.ai-agents/<role>.md
```

### Adding a new role to an existing project

After `teamupdate`, scaffold missing agent files without touching existing ones:

```bash
cd /path/to/your-project
teaminit
```

Then add the new entry to `.ai-config.yaml`:

```yaml
- name: security-engineer
  prompt: .ai-agents/security-engineer.md
  scale: auto
  min: 0
  max: 1
```

### What survives an update

| Data | Survives `teamupdate` | Survives `teamclean` |
|---|---|---|
| `tasks/tasks.json` | yes | no |
| `outputs/` | yes | no |
| `.ai-state/lessons.json` | yes | no |
| `~/.claude/.../memory/lesson_*.md` | yes | **yes** |
| `.ai-agents/*.md` (project overrides) | yes | no |
| `.ai-config.yaml` | yes | no |

Claude Code memory lessons are never touched by any team command and persist permanently.

## Claude Code Skills

Three skills are installed into `~/.claude/skills/` during setup (and updated by `teamupdate`):

| Skill | Trigger | Description |
|---|---|---|
| `reflect` | `/reflect`, "세션 정리", "wrap up" | Session wrap-up: inspect tasks/outputs, suggest lessons to record |
| `blueprint` | `/blueprint`, "설계서", "에이전트 설계" | Interview → agent system design document generator |
| `deep-dive` | `/deep-dive`, "요구사항 정리", "기획서" | Multi-round requirements interview → spec writing |

## Quick start

```bash
git clone https://github.com/picory/tmux-team-agent.git
cd tmux-team-agent
./setup.sh

cd /path/to/your-project
teamstart
```

Then talk to the `leader` pane and let the watcher orchestrate worker panes in `tmux`.

## License

MIT. See [LICENSE](LICENSE).
