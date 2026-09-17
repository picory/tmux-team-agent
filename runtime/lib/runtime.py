#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or "project"


def runtime_home() -> Path:
    value = os.environ.get("TMUX_RUNTIME_HOME") or str(Path.home() / ".tmux-runtime")
    return Path(value).expanduser()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return deepcopy(default)
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError:
        return deepcopy(default)


def save_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        temp_name = handle.name
    os.replace(temp_name, path)


def contains_doc_hint(text: str) -> bool:
    normalized = text.lower()
    return any(
        hint in normalized
        for hint in [
            "docs",
            "readme",
            "runbook",
            "guide",
            "report",
            "documentation",
            "문서",
            "리포트",
            "설명",
        ]
    )


def shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def get_free_memory_mb() -> int | None:
    """Return available memory in MB, or None if unavailable."""
    import platform
    system = platform.system()
    if system == "Darwin":
        try:
            ps = subprocess.run(["sysctl", "-n", "hw.pagesize"], capture_output=True, text=True, check=False)
            page_size = int(ps.stdout.strip()) if ps.returncode == 0 else 4096
            vm = subprocess.run(["vm_stat"], capture_output=True, text=True, check=False)
            if vm.returncode != 0:
                return None
            free_pages = 0
            for line in vm.stdout.splitlines():
                for prefix in ("Pages free:", "Pages inactive:"):
                    if line.startswith(prefix):
                        free_pages += int(line.split(":")[1].strip().rstrip("."))
            return (free_pages * page_size) // (1024 * 1024)
        except (ValueError, IndexError, OSError):
            return None
    if system == "Linux":
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
        except (OSError, ValueError, IndexError):
            return None
    return None


def run(cmd: list[str], capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        capture_output=capture,
    )


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def detect_mux() -> str:
    preferred = os.environ.get("TMUX_BIN")
    if preferred:
        if command_exists(preferred):
            return preferred
        raise SystemExit(f"{preferred} is configured but was not found.")
    if command_exists("tmux"):
        return "tmux"
    raise SystemExit("tmux is required for this runtime but was not found.")


def session_name(project_dir: Path) -> str:
    return f"ai-{safe_name(project_dir.name)}"


@dataclass
class Config:
    project: str
    agents: list[dict[str, Any]]
    paths: dict[str, str]
    limits: dict[str, Any]
    docs: dict[str, Any]
    verification: dict[str, Any]
    review: dict[str, Any]

    @property
    def task_dir(self) -> str:
        return self.paths.get("tasks", "./tasks")

    @property
    def outputs_dir(self) -> str:
        return self.paths.get("outputs", "./outputs")


def parse_scalar(value: str) -> Any:
    if value in {"true", "false"}:
        return value == "true"
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def parse_ai_config(path: Path) -> Config:
    lines = path.read_text(encoding="utf-8").splitlines()
    root: dict[str, Any] = {}
    current_section: str | None = None
    current_item: dict[str, Any] | None = None

    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()

        if indent == 0 and ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value:
                root[key] = parse_scalar(value)
                current_section = None
                current_item = None
            else:
                if key == "agents":
                    root[key] = []
                else:
                    root[key] = {}
                current_section = key
                current_item = None
            continue

        if current_section == "agents" and stripped.startswith("- "):
            item = {}
            root["agents"].append(item)
            current_item = item
            payload = stripped[2:]
            if payload and ":" in payload:
                key, value = payload.split(":", 1)
                item[key.strip()] = parse_scalar(value.strip())
            continue

        if current_section == "agents" and current_item and ":" in stripped:
            key, value = stripped.split(":", 1)
            current_item[key.strip()] = parse_scalar(value.strip())
            continue

        if (
            current_section
            and current_section != "agents"
            and isinstance(root.get(current_section), dict)
            and ":" in stripped
        ):
            key, value = stripped.split(":", 1)
            root[current_section][key.strip()] = parse_scalar(value.strip())
            continue

    return Config(
        project=str(root.get("project", path.parent.name)),
        agents=list(root.get("agents", [])),
        paths=dict(root.get("paths", {})),
        limits=dict(root.get("limits", {})),
        docs=dict(root.get("docs", {})),
        verification=dict(root.get("verification", {})),
        review=dict(root.get("review", {})),
    )


def template_root() -> Path:
    return Path(__file__).resolve().parents[1].parent / "templates"


def prompt_root() -> Path:
    return Path(__file__).resolve().parents[1] / "prompts"


def ensure_project(project_dir: Path) -> Config:
    tmpl = template_root()
    config_path = project_dir / ".ai-config.yaml"
    if not config_path.exists():
        content = read_text(tmpl / ".ai-config.yaml").replace("__PROJECT_NAME__", project_dir.name)
        write_text(config_path, content)

    for relative in [
        ".ai-agents/leader.md",
        ".ai-agents/product-manager.md",
        ".ai-agents/ux-designer.md",
        ".ai-agents/backend-coder.md",
        ".ai-agents/frontend-coder.md",
        ".ai-agents/mobile-coder.md",
        ".ai-agents/desktop-coder.md",
        ".ai-agents/embedded-coder.md",
        ".ai-agents/crawler-coder.md",
        ".ai-agents/ai-ml-engineer.md",
        ".ai-agents/data-engineer.md",
        ".ai-agents/devops-engineer.md",
        ".ai-agents/cloud-architect.md",
        ".ai-agents/network-engineer.md",
        ".ai-agents/dba.md",
        ".ai-agents/test-harness-engineer.md",
        ".ai-agents/performance-engineer.md",
        ".ai-agents/security-engineer.md",
        ".ai-agents/reviewer.md",
        ".ai-agents/qa.md",
        ".ai-agents/docs-writer.md",
        "tasks/tasks.json",
        ".ai-state/agent_pool.json",
    ]:
        target = project_dir / relative
        if not target.exists():
            write_text(target, read_text(tmpl / relative))

    ensure_dir(project_dir / "outputs")
    ensure_dir(project_dir / ".claude")
    return parse_ai_config(config_path)


def claude_available(project_dir: Path) -> bool:
    if not command_exists("claude"):
        return False
    return (project_dir / ".claude").exists() or (Path.home() / ".claude").exists()


def skills_root() -> Path:
    return Path(__file__).resolve().parents[1] / "skills"


def workflows_root() -> Path:
    return Path(__file__).resolve().parents[1] / "workflows"


def codex_available() -> bool:
    return command_exists("codex")


def install_skills(target_dir: Path | None = None) -> list[str]:
    """Copy runtime skills to ~/.claude/skills/ (or target_dir).

    Only installs skills that do not already exist so user edits are preserved.
    Returns list of installed skill names.
    """
    src_root = skills_root()
    dest_root = target_dir or (Path.home() / ".claude" / "skills")
    ensure_dir(dest_root)
    installed = []
    if not src_root.is_dir():
        return installed
    for skill_dir in sorted(src_root.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_name = skill_dir.name
        dest_skill = dest_root / skill_name
        skill_file_src = skill_dir / "SKILL.md"
        if not skill_file_src.exists():
            continue
        if dest_skill.exists():
            continue  # already installed — don't overwrite
        ensure_dir(dest_skill)
        import shutil as _shutil
        _shutil.copytree(str(skill_dir), str(dest_skill), dirs_exist_ok=True)
        installed.append(skill_name)
    return installed


def reinstall_skills(target_dir: Path | None = None) -> list[str]:
    """Force-overwrite runtime skills (used by teamupdate)."""
    src_root = skills_root()
    dest_root = target_dir or (Path.home() / ".claude" / "skills")
    ensure_dir(dest_root)
    updated = []
    if not src_root.is_dir():
        return updated
    import shutil as _shutil
    for skill_dir in sorted(src_root.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_name = skill_dir.name
        skill_file_src = skill_dir / "SKILL.md"
        if not skill_file_src.exists():
            continue
        dest_skill = dest_root / skill_name
        if dest_skill.exists():
            _shutil.rmtree(str(dest_skill))
        _shutil.copytree(str(skill_dir), str(dest_skill))
        updated.append(skill_name)
    return updated


def install_commit_hook(project_dir: Path) -> bool:
    """Install commit-session.sh Stop hook into a project.

    Copies the hook template to .claude/hooks/ and registers it in
    .claude/settings.json. Safe to call multiple times (idempotent).
    Returns True if anything changed.
    """
    hooks_dir = project_dir / ".claude" / "hooks"
    ensure_dir(hooks_dir)

    # Copy hook script
    src = runtime_home() / "hooks" / "commit-session.sh"
    if not src.exists():
        # Try finding it relative to runtime.py's own location (dev mode)
        src = Path(__file__).parent.parent / "hooks" / "commit-session.sh"
    if not src.exists():
        return False

    dest = hooks_dir / "commit-session.sh"
    import shutil as _shutil
    _shutil.copy2(str(src), str(dest))
    dest.chmod(0o755)

    # Register in settings.json
    settings_path = project_dir / ".claude" / "settings.json"
    settings = load_json(settings_path, {})

    hooks = settings.setdefault("hooks", {})
    stop_hooks = hooks.setdefault("Stop", [])

    hook_command = "$CLAUDE_PROJECT_DIR/.claude/hooks/commit-session.sh"
    hook_entry = {"type": "command", "command": hook_command}

    # Check if already registered
    for group in stop_hooks:
        for h in group.get("hooks", []):
            if h.get("command") == hook_command:
                return False  # already installed

    if stop_hooks:
        stop_hooks[0].setdefault("hooks", []).append(hook_entry)
    else:
        stop_hooks.append({"hooks": [hook_entry]})

    save_json(settings_path, settings)
    return True


def remove_commit_hook(project_dir: Path) -> bool:
    """Remove commit-session.sh Stop hook from a project.

    Removes the hook script and deregisters it from settings.json.
    Returns True if anything changed.
    """
    hook_command = "$CLAUDE_PROJECT_DIR/.claude/hooks/commit-session.sh"
    changed = False

    dest = project_dir / ".claude" / "hooks" / "commit-session.sh"
    if dest.exists():
        dest.unlink()
        changed = True

    settings_path = project_dir / ".claude" / "settings.json"
    if not settings_path.exists():
        return changed

    settings = load_json(settings_path, {})
    stop_hooks = settings.get("hooks", {}).get("Stop", [])
    new_stop = []
    for group in stop_hooks:
        filtered = [h for h in group.get("hooks", []) if h.get("command") != hook_command]
        if filtered:
            new_stop.append({**group, "hooks": filtered})
        elif len(group) > 1:  # group has other keys besides "hooks"
            new_stop.append({**group, "hooks": []})
        # else drop the now-empty group
        if len(group.get("hooks", [])) != len(filtered):
            changed = True

    if changed:
        settings.setdefault("hooks", {})["Stop"] = new_stop
        if not new_stop:
            del settings["hooks"]["Stop"]
        if not settings.get("hooks"):
            del settings["hooks"]
        save_json(settings_path, settings)

    return changed


def setup_claude_settings(project_dir: Path) -> None:
    """Create .claude/settings.json if it doesn't exist."""
    settings_path = project_dir / ".claude" / "settings.json"
    if settings_path.exists():
        return
    ensure_dir(settings_path.parent)
    settings = {
        "permissions": {
            "allow": [
                "Bash(git:*)",
                "Bash(python3:*)",
                "Bash(tmux:*)",
                "Read",
                "Write",
                "Edit",
                "Glob",
                "Grep",
            ],
            "deny": [],
        },
    }
    save_json(settings_path, settings)


def setup_claude_md(project_dir: Path, cfg: Config) -> None:
    """Create CLAUDE.md with project + team context if it doesn't exist."""
    claude_md = project_dir / "CLAUDE.md"
    if claude_md.exists():
        return
    roles = [str(a.get("name")) for a in cfg.agents if a.get("name") != "leader"]
    roles_list = "\n".join(f"- `{r}`" for r in roles)
    content = f"""# {cfg.project}

## 프로젝트 개요

(여기에 프로젝트 설명을 추가하세요)

## 팀 에이전트 역할

{roles_list}

## 런타임 커맨드

```bash
# 태스크 큐에 작업 추가
python3 ~/.tmux-runtime/lib/runtime.py enqueue \\
  --project-dir $PWD --role <role> --text "<task description>"

# 현재 상태 확인
python3 ~/.tmux-runtime/lib/runtime.py status --project-dir $PWD

# 교훈 기록
python3 ~/.tmux-runtime/lib/runtime.py lesson \\
  --project-dir $PWD --role <role> --title "<title>" --detail "<detail>"
```

## 에이전트 참조 규칙

모든 에이전트는 **작업 시작 전 반드시 이 CLAUDE.md를 확인**하고 아래 원칙을 따른다.

## 규칙

- 구현 전 요구사항을 명확히 한다
- 태스크는 tasks/tasks.json에서 관리한다
- 아웃풋은 outputs/<task-id>.md에 기록한다
"""
    write_text(claude_md, content)


_WORK_PRINCIPLES = """\n## 작업 원칙

이 프로젝트의 모든 버그 수정/기능 구현은 목표 지향 방식으로 수행한다.

### 코딩 전 원칙

**구현 전에 생각하라 (Think Before Coding)**
- 가정과 불명확한 점을 구현 전에 명시적으로 드러낸다.
- 해석 사이에서 조용히 선택하지 않는다. 모호하면 질문한다.
- 확인 가능한 성공 기준을 먼저 정의한다. ("버그 수정" → "버그를 재현하는 테스트를 작성한 뒤 통과시킨다")

**단순함을 우선하라 (Simplicity First)**
- 문제를 해결하는 최소한의 코드만 작성한다.
- 추측적 기능, 불필요한 추상화, 요청받지 않은 유연성을 추가하지 않는다.
- 절반 길이로 쓸 수 있다면 다시 작성한다.

**외과적으로 수정하라 (Surgical Changes)**
- 기존 코드 편집 시 필요한 부분만 건드린다.
- 기존 스타일을 유지하고, 변경으로 불필요해진 import/변수만 제거한다.
- 요청받지 않은 한 기존 dead code를 그대로 둔다.

### 완료 조건

기본 루프: 분석 → 계획 → 구현 → 테스트 → 실패 시 보완 → 완료 보고

- 근본 원인이 설명 가능해야 한다.
- 관련 테스트가 통과해야 한다.
- lint/typecheck/build가 가능한 경우 통과해야 한다.
- 테스트를 삭제하거나 약화하지 않는다.
- 임시방편, 하드코딩, 에러 무시는 금지한다.
- 변경 범위는 목표 달성에 필요한 최소 범위로 제한한다.

### 완료 보고

- 원인
- 변경 파일
- 수정 내용
- 실행한 검증 명령
- 결과
- 남은 리스크
"""


def _append_work_principles(claude_md: Path) -> None:
    existing = read_text(claude_md) if claude_md.exists() else ""
    if "## 작업 원칙" not in existing:
        with claude_md.open("a", encoding="utf-8") as f:
            f.write(_WORK_PRINCIPLES)


def _ask(prompt: str, default: str = "") -> str:
    """Interactive prompt with default value."""
    if default:
        response = input(f"{prompt} [{default}]: ").strip()
        return response or default
    return input(f"{prompt}: ").strip()


def _set_config_flag(config_path: Path, section: str, key: str, value: str) -> None:
    """Update a key inside a yaml section in .ai-config.yaml (simple line-based)."""
    if not config_path.exists():
        return
    lines = config_path.read_text(encoding="utf-8").splitlines(keepends=True)
    in_section = False
    key_line = f"  {key}:"
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == f"{section}:":
            in_section = True
            continue
        if in_section:
            if line and not line[0].isspace():
                in_section = False
                continue
            if stripped.startswith(f"{key}:"):
                lines[i] = f"  {key}: {value}\n"
                config_path.write_text("".join(lines), encoding="utf-8")
                return
    # key not found — append under section header
    for i, line in enumerate(lines):
        if line.strip() == f"{section}:":
            lines.insert(i + 1, f"  {key}: {value}\n")
            config_path.write_text("".join(lines), encoding="utf-8")
            return


def _confirm(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    response = input(f"{prompt} [{hint}]: ").strip().lower()
    if not response:
        return default
    return response in ("y", "yes")


def setup_wiki_llm(project_dir: Path, project_name: str, wiki_dir: str = "wiki-llm") -> None:
    """Create wiki directory structure for LLM-native documentation."""
    today = datetime.now().strftime("%Y-%m-%d")
    base = project_dir / wiki_dir

    claude_md = """\
# Wiki-LLM — Claude Code 유지보수 지침

이 디렉토리는 **{project}** 프로젝트의 LLM-native 지식 베이스다.
Andrej Karpathy의 wiki-llm 개념을 따른다: RAG가 아닌 **지속적으로 누적되는 구조화 문서**.

---

## 디렉토리 구조

```
{wiki_dir}/
├── CLAUDE.md          ← 이 파일: 유지보수 규칙
├── schema/SCHEMA.md   ← 위키 규약 전체 정의
├── raw/               ← 불변 원본 자료 (LLM이 쓰지 않음)
│   ├── 01-requirements/   # 요구사항 원문
│   └── 02-decisions/      # 아키텍처 결정 기록 (ADR)
└── wiki/              ← LLM이 유지보수하는 지식 페이지
    ├── index.md           # 전체 페이지 카탈로그
    ├── log.md             # 위키 변경 이력
    ├── domain/            # 도메인 개념·용어 정의
    └── feature/           # 기능별 상세 명세
```

---

## Claude Code가 해야 할 일

### 언제 wiki를 업데이트하나

- 새로운 기능을 구현했을 때 → `wiki/feature/` 해당 파일 추가·수정
- 도메인 개념이 바뀌거나 추가됐을 때 → `wiki/domain/glossary.md` 수정
- 아키텍처 결정이 내려졌을 때 → `raw/02-decisions/` 에 ADR 추가
- 기존 문서가 코드와 어긋날 때 → 코드 기준으로 wiki 수정

### 언제 raw를 건드리나

- 절대 수정하지 않는다. raw는 원본 기록이다.
- 새 요구사항이나 결정이 생기면 파일을 새로 추가한다 (파일명: `<topic>-YYYYMMDD.md`).

### 링크 규약

- 같은 wiki 내 참조: `[[glossary]]`, `[[auto-scaling]]`
- raw 참조: `[원본](../raw/02-decisions/example-20260101.md)`
- 외부 코드 참조: `파일명:줄번호` (행 번호 포함)

### 업데이트 후 반드시 할 일

1. `wiki/index.md` 카탈로그 최신화
2. `wiki/log.md` 맨 위에 변경 항목 한 줄 추가

---

## 작성 스타일

- 독자는 이 프로젝트를 처음 보는 Claude (또는 신규 개발자)
- 결론부터, 그 다음 이유
- 코드 예시는 실제 코드 기준, 추측 금지
- 테이블 > 긴 산문
- 섹션당 200자 이내 권장
""".replace("{project}", project_name).replace("{wiki_dir}", wiki_dir)

    schema_md = """\
# Wiki 규약 (SCHEMA)

## 파일 명명

| 위치 | 규칙 | 예시 |
|------|------|------|
| `raw/` | `<topic>-YYYYMMDD.md` | `init-20260101.md` |
| `wiki/domain/` | 개념명 kebab-case | `glossary.md` |
| `wiki/feature/` | 기능명 kebab-case | `auto-scaling.md` |

## 페이지 프론트매터

```markdown
> 최종 수정: YYYY-MM-DD | 상태: draft / stable / deprecated
```

상태 정의:
- `draft` — 작성 중, 코드와 불일치 가능
- `stable` — 코드와 일치 확인됨
- `deprecated` — 제거된 기능, 역사 기록용

## 링크

- wiki 내부: `[[페이지명]]` (파일 확장자 제외)
- raw 원본: 상대 경로 마크다운 링크
- 코드 위치: `파일:줄번호` 형식

## index.md 항목 형식

```
- [페이지 제목](경로) — 한 줄 요약
```

## log.md 항목 형식

```
- YYYY-MM-DD: <변경 내용> (`파일명`)
```
"""

    index_md = f"""\
> 최종 수정: {today} | 상태: stable

# {project_name} 위키 카탈로그

## Domain
- [Glossary](domain/glossary.md) — 핵심 용어 정의

## Feature
(추가 예정)
"""

    log_md = f"""\
# 위키 변경 이력

- {today}: 위키 초기 생성
"""

    glossary_md = f"""\
> 최종 수정: {today} | 상태: draft

# 용어 사전

| 용어 | 정의 |
|------|------|
| (추가 예정) | |
"""

    files = {
        base / "CLAUDE.md": claude_md,
        base / "schema" / "SCHEMA.md": schema_md,
        base / "wiki" / "index.md": index_md,
        base / "wiki" / "log.md": log_md,
        base / "wiki" / "domain" / "glossary.md": glossary_md,
    }
    dirs = [
        base / "raw" / "01-requirements",
        base / "raw" / "02-decisions",
        base / "wiki" / "feature",
    ]

    for d in dirs:
        ensure_dir(d)
    for path, content in files.items():
        if not path.exists():
            write_text(path, content)


def cmd_wizard(project_dir: Path) -> None:
    """First-run interactive setup wizard."""
    print("\n" + "=" * 60)
    print("  tmux-team-agent — 최초 설정 마법사")
    print("=" * 60)
    print(f"  프로젝트 디렉토리: {project_dir}\n")

    # ── Step 1: Doctor ───────────────────────────────────────────
    print("[1/7] 환경 점검")
    run_doctor = _confirm("  환경 점검을 실행할까요?", default=True)
    if run_doctor:
        ok = (cmd_doctor(project_dir) == 0)
        if not ok:
            proceed = _confirm("\n  일부 점검이 실패했습니다. 계속 진행할까요?", default=False)
            if not proceed:
                print("  설정을 중단합니다. 문제를 해결한 후 다시 실행하세요.")
                return
    print()

    # ── Step 2: Project name ────────────────────────────────────
    print("[2/7] 프로젝트 설정")
    config_path = project_dir / ".ai-config.yaml"
    default_name = project_dir.name
    project_name = _ask("  프로젝트명", default=default_name)

    if not config_path.exists():
        tmpl = template_root()
        content = read_text(tmpl / ".ai-config.yaml").replace("__PROJECT_NAME__", project_name)
        write_text(config_path, content)
        print(f"  .ai-config.yaml 생성됨")

    cfg = parse_ai_config(config_path)

    # scaffold agent files
    for relative in [
        ".ai-agents/leader.md", ".ai-agents/product-manager.md", ".ai-agents/ux-designer.md",
        ".ai-agents/backend-coder.md", ".ai-agents/frontend-coder.md", ".ai-agents/mobile-coder.md",
        ".ai-agents/desktop-coder.md", ".ai-agents/embedded-coder.md", ".ai-agents/crawler-coder.md",
        ".ai-agents/ai-ml-engineer.md", ".ai-agents/data-engineer.md", ".ai-agents/devops-engineer.md",
        ".ai-agents/cloud-architect.md", ".ai-agents/network-engineer.md", ".ai-agents/dba.md",
        ".ai-agents/test-harness-engineer.md", ".ai-agents/performance-engineer.md",
        ".ai-agents/security-engineer.md", ".ai-agents/reviewer.md", ".ai-agents/qa.md",
        ".ai-agents/docs-writer.md", "tasks/tasks.json", ".ai-state/agent_pool.json",
    ]:
        target = project_dir / relative
        src = template_root() / relative
        if not target.exists() and src.exists():
            write_text(target, read_text(src))
    ensure_dir(project_dir / "outputs")
    ensure_dir(project_dir / ".claude")
    print(f"  팀 에이전트 파일 초기화 완료")
    print()

    # ── Step 3: Claude settings ─────────────────────────────────
    print("[3/7] Claude 설정")
    setup_claude_settings(project_dir)
    print(f"  .claude/settings.json {'생성됨' if not (project_dir / '.claude' / 'settings.json').exists() else '이미 존재'}")
    setup_claude_md(project_dir, cfg)
    print(f"  CLAUDE.md {'생성됨' if not (project_dir / 'CLAUDE.md').exists() else '이미 존재'}")
    if _confirm("  개발 규칙(작업 원칙)을 CLAUDE.md에 추가할까요?", default=True):
        _append_work_principles(project_dir / "CLAUDE.md")
        print("  작업 원칙 추가됨")
    print()

    # ── Step 4: Skills ──────────────────────────────────────────
    print("[4/7] 스킬 설치")
    install = _confirm("  reflect / blueprint / deep-dive 스킬을 ~/.claude/skills/ 에 설치할까요?", default=True)
    if install:
        installed = install_skills()
        if installed:
            print(f"  설치됨: {', '.join(installed)}")
        else:
            print("  모든 스킬이 이미 설치되어 있습니다")
    print()

    # ── Step 5: Wiki-LLM ────────────────────────────────────────
    print("[5/7] 문서 관리 (LLM Wiki)")
    print("  LLM-native 위키 구조를 생성합니다.")
    print("  에이전트가 기능 구현 후 자동으로 wiki를 업데이트합니다.")
    wiki_install = _confirm("  LLM wiki 문서 구조를 초기화할까요?", default=True)
    if wiki_install:
        wiki_dir_name = _ask("  wiki 디렉토리명", default="wiki-llm")
        wiki_dir_path = project_dir / wiki_dir_name
        if wiki_dir_path.exists():
            print(f"  이미 {wiki_dir_name}/ 디렉토리가 존재합니다")
        else:
            setup_wiki_llm(project_dir, cfg.project, wiki_dir_name)
            print(f"  {wiki_dir_name}/ 생성 완료")
        _set_config_flag(config_path, "docs", "wiki_llm", "true")
        _set_config_flag(config_path, "docs", "wiki_dir", wiki_dir_name)
    print()

    # ── Step 6: Commit hook ──────────────────────────────────────
    print("[6/7] 세션 자동 커밋 훅")
    print("  Claude Code 세션 종료 시 변경사항을 자동으로 WIP 커밋합니다.")
    print("  teamstart 에이전트가 실행 중이면 AI가 커밋 메시지를 생성합니다.")
    hook_install = _confirm("  commit-session.sh Stop 훅을 설치할까요?", default=False)
    if hook_install:
        ok = install_commit_hook(project_dir)
        print("  훅 설치됨 (.claude/hooks/commit-session.sh)" if ok else "  이미 설치되어 있습니다")
    print()

    # ── Step 7: Env vars ────────────────────────────────────────
    print("[7/7] 환경 변수")
    print("  런타임 동작을 조정하려면 아래 환경변수를 .env 또는 셸 프로파일에 추가하세요:\n")
    print("    AI_WATCH_INTERVAL=5        # watcher 폴링 간격 (초)")
    print("    AI_IDLE_TTL_SECONDS=120    # idle 에이전트 종료까지 대기 시간 (초)")
    print("    TMUX_BIN=tmux              # 커스텀 tmux 바이너리")
    print("    TMUX_RUNTIME_HOME=~/.tmux-runtime  # 런타임 설치 경로")

    create_env = _confirm("\n  .env.example 파일을 생성할까요?", default=True)
    if create_env:
        env_example = project_dir / ".env.example"
        if not env_example.exists():
            write_text(env_example, "\n".join([
                "# tmux-team-agent 환경 변수",
                "# 필요한 항목을 .env 또는 셸 프로파일에 복사하여 사용하세요",
                "",
                "# AI_WATCH_INTERVAL=5",
                "# AI_IDLE_TTL_SECONDS=120",
                "# TMUX_BIN=tmux",
                "# TMUX_RUNTIME_HOME=~/.tmux-runtime",
                "",
            ]))
            print("  .env.example 생성됨")

    # ── Done ────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  설정 완료!")
    print("=" * 60)
    print(f"  프로젝트: {project_name}")
    print(f"  에이전트: {len(cfg.agents)}개 역할 구성됨")
    print(f"  스킬: /reflect  /blueprint  /deep-dive")
    print()


# ---------------------------------------------------------------------------
# Lessons — record mistakes to prevent recurrence
# ---------------------------------------------------------------------------

def claude_project_memory_path(project_dir: Path) -> Path:
    """Return the Claude Code memory directory for a given project path.

    Claude Code encodes the absolute project path by replacing every '/' and '_'
    with '-', then uses that as the directory name under ~/.claude/projects/.
    Example: /Volumes/m2DATA/my_project -> -Volumes-m2DATA-my-project
    """
    encoded = str(project_dir.resolve()).replace("/", "-").replace("_", "-")
    return Path.home() / ".claude" / "projects" / encoded / "memory"


def lessons_path(project_dir: Path) -> Path:
    return project_dir / ".ai-state" / "lessons.json"


def load_lessons(project_dir: Path) -> dict:
    return load_json(lessons_path(project_dir), {"lessons": []})


def save_lessons(project_dir: Path, data: dict) -> None:
    save_json(lessons_path(project_dir), data)


def record_lesson(
    project_dir: Path,
    role: str | None,
    title: str,
    detail: str,
    source_task_id: str | None = None,
) -> str:
    """Save a lesson to .ai-state/lessons.json and to Claude Code memory."""
    lesson_id = uuid.uuid4().hex[:8]
    entry = {
        "id": lesson_id,
        "role": role,
        "title": title.strip(),
        "detail": detail.strip(),
        "created_at": now_iso(),
        "source_task_id": source_task_id,
    }

    # --- project-local lessons.json ---
    data = load_lessons(project_dir)
    data["lessons"].append(entry)
    save_lessons(project_dir, data)

    # --- Claude Code memory (persistent across sessions) ---
    mem_dir = claude_project_memory_path(project_dir)
    ensure_dir(mem_dir)
    role_label = role or "all-roles"
    scope_line = f"Applies to: **{role}** agent" if role else "Applies to: **all agents**"
    mem_content = "\n".join([
        "---",
        f"name: Lesson {lesson_id}: {entry['title']}",
        f"description: {role_label} — {entry['title']}",
        "type: feedback",
        "---",
        "",
        entry["detail"],
        "",
        f"**Why:** Recorded from {'task ' + source_task_id if source_task_id else 'manual entry'} in project `{project_dir.name}`.",
        f"**How to apply:** {scope_line}. Check this before starting similar work.",
    ])
    write_text(mem_dir / f"lesson_{lesson_id}.md", mem_content)

    # --- update MEMORY.md index ---
    memory_index = mem_dir / "MEMORY.md"
    existing = memory_index.read_text(encoding="utf-8") if memory_index.exists() else "# Memory\n"
    line = f"- [Lesson {lesson_id}: {entry['title']}](lesson_{lesson_id}.md) — {role_label}: {entry['title']}\n"
    write_text(memory_index, existing.rstrip("\n") + "\n" + line)

    return lesson_id


def list_lessons_text(project_dir: Path, role: str | None = None) -> str:
    data = load_lessons(project_dir)
    lessons = data.get("lessons", [])
    if role:
        lessons = [l for l in lessons if l.get("role") in (role, None)]
    if not lessons:
        return "No lessons recorded yet."
    lines = [f"Lessons ({len(lessons)} total):"]
    for l in lessons:
        r = l.get("role") or "all"
        lines.append(f"  [{l['id']}] ({r}) {l['title']}")
        lines.append(f"         {l['detail'][:120]}")
    return "\n".join(lines)


def lessons_for_role(project_dir: Path, role: str) -> list[dict]:
    """Return lessons applicable to a role (role-specific + global)."""
    data = load_lessons(project_dir)
    return [l for l in data.get("lessons", []) if l.get("role") in (role, None)]


def merge_prompt(project_dir: Path, role: str) -> str:
    base_path = prompt_root() / f"{role}.base.md"
    project_path = project_dir / ".ai-agents" / f"{role}.md"
    chunks: list[str] = []
    if base_path.exists():
        chunks.append(read_text(base_path).strip())
    if project_path.exists():
        chunks.append(read_text(project_path).strip())

    # Inject lessons learned for this role
    applicable = lessons_for_role(project_dir, role)
    if applicable:
        lesson_lines = ["## Lessons learned — do not repeat these mistakes"]
        for l in applicable:
            lesson_lines.append(f"- **{l['title']}**: {l['detail']}")
        chunks.append("\n".join(lesson_lines))

    return "\n\n".join(chunk for chunk in chunks if chunk).strip()


def project_paths(project_dir: Path, cfg: Config) -> dict[str, Path]:
    task_dir = (project_dir / cfg.task_dir).resolve()
    outputs_dir = (project_dir / cfg.outputs_dir).resolve()
    state_dir = (project_dir / ".ai-state").resolve()
    return {
        "tasks_file": task_dir / "tasks.json",
        "outputs_dir": outputs_dir,
        "agent_pool": state_dir / "agent_pool.json",
    }


def normalize_task(task: dict[str, Any]) -> dict[str, Any]:
    created_at = task.get("created_at") or now_iso()
    updated_at = task.get("updated_at") or created_at
    role = str(task.get("role", "backend-coder"))
    title = str(task.get("title", "")).strip()
    task.setdefault("id", f"{role}-{uuid.uuid4().hex[:8]}")
    task["role"] = role
    task["title"] = title
    task["status"] = str(task.get("status", "pending"))
    task["created_at"] = created_at
    task["updated_at"] = updated_at
    task.setdefault("priority", "normal")
    task.setdefault("scope", "task")
    task.setdefault("paths", [])
    task.setdefault("depends_on", [])
    task.setdefault("result", None)
    task.setdefault("created_by", "leader")
    task.setdefault("parent_task_id", None)
    task.setdefault("root_task_id", task["id"])
    task.setdefault("followups", [])
    task.setdefault("artifacts", [])
    task.setdefault("attempts", 0)
    task.setdefault("last_error", None)
    task.setdefault("agent", None)
    task.setdefault("started_at", None)
    task.setdefault("completed_at", None)
    task.setdefault(
        "policy",
        {
            "auto_review": role.endswith("-coder") or role == "coder",
            "auto_qa": role.endswith("-coder") or role == "coder",
            "auto_docs": contains_doc_hint(title),
        },
    )
    task.setdefault("metadata", {})
    return task


def normalize_pool(pool: dict[str, Any]) -> dict[str, Any]:
    pool.setdefault("agents", [])
    return pool


def load_state(project_dir: Path, cfg: Config) -> tuple[dict[str, Any], dict[str, Any]]:
    paths = project_paths(project_dir, cfg)
    tasks = load_json(paths["tasks_file"], {"tasks": []})
    pool = load_json(paths["agent_pool"], {"agents": []})
    tasks.setdefault("tasks", [])
    tasks["tasks"] = [normalize_task(task) for task in tasks["tasks"]]
    pool = normalize_pool(pool)
    return tasks, pool


def save_state(project_dir: Path, cfg: Config, tasks: dict[str, Any], pool: dict[str, Any]) -> None:
    paths = project_paths(project_dir, cfg)
    save_json(paths["tasks_file"], tasks)
    save_json(paths["agent_pool"], pool)


def find_agent_cfg(cfg: Config, role: str) -> dict[str, Any] | None:
    for item in cfg.agents:
        if item.get("name") == role:
            return item
    return None


def default_intake_role(cfg: Config) -> str:
    preferred = [
        "backend-coder",
        "frontend-coder",
        "desktop-coder",
        "crawler-coder",
        "coder",
    ]
    configured = {item.get("name") for item in cfg.agents}
    for role in preferred:
        if role in configured:
            return role
    for item in cfg.agents:
        role = str(item.get("name"))
        if role not in {"leader", "reviewer", "qa", "docs-writer", "security-engineer", "performance-engineer", "cloud-architect", "product-manager", "ux-designer"}:
            return role
    return "reviewer"


def infer_role_from_text(cfg: Config, text: str) -> str:
    normalized = text.lower()
    configured = {str(item.get("name")) for item in cfg.agents}
    scored: dict[str, int] = {}

    role_keywords = {
        "backend-coder": [
            "api",
            "backend",
            "server",
            "laravel",
            "php",
            "db",
            "database",
            "mysql",
            "redis",
            "queue",
            "horizon",
            "graphql",
            "auth",
            "webhook",
            "runtime",
            "state",
            ".py",
            "script",
        ],
        "frontend-coder": [
            "frontend",
            "ui",
            "ux",
            "next.js",
            "nextjs",
            "react",
            "component",
            "page",
            "layout",
            "tailwind",
            "shadcn",
            "css",
            "browser",
            "webapp/frontend",
            ".tsx",
            ".jsx",
        ],
        "desktop-coder": [
            "desktop",
            "tauri",
            "rust",
            "tray",
            "native",
            "window",
            "terminal",
            "mux",
            "tmux",
            "desktopapp",
            "src-tauri",
            ".rs",
        ],
        "crawler-coder": [
            "crawler",
            "scrape",
            "scraping",
            "crawl",
            "playwright",
            "automation",
            "bot",
            "selenium",
            "collect",
            "extract",
            "monitor",
            "watcher",
            "polling",
            "crawler/",
        ],
        "reviewer": [
            "review",
            "audit",
            "regression",
            "bug risk",
            "pr review",
            "코드 리뷰",
            "검토",
        ],
        "qa": [
            "qa",
            "test",
            "verify",
            "verification",
            "repro",
            "scenario",
            "e2e",
            "playtest",
            "check flow",
            "검증",
            "재현",
            "테스트",
        ],
        "docs-writer": [
            "docs",
            "readme",
            "runbook",
            "guide",
            "document",
            "documentation",
            "report",
            "spec",
            "설명서",
            "문서",
            "리포트",
        ],
        "product-manager": [
            "prd",
            "product",
            "requirement",
            "requirements",
            "user story",
            "user stories",
            "roadmap",
            "feature spec",
            "acceptance criteria",
            "기획",
            "요구사항",
            "기능 명세",
        ],
        "ux-designer": [
            "ux",
            "wireframe",
            "user journey",
            "user flow",
            "interaction design",
            "accessibility",
            "design system",
            "prototype",
            "사용자 경험",
            "와이어프레임",
            "디자인",
        ],
        "mobile-coder": [
            "ios",
            "android",
            "react native",
            "flutter",
            "mobile",
            "app store",
            "play store",
            "push notification",
            "deep link",
            "모바일",
            ".dart",
            ".swift",
            ".kotlin",
        ],
        "ai-ml-engineer": [
            "machine learning",
            "ml",
            "model training",
            "inference",
            "pytorch",
            "tensorflow",
            "hugging face",
            "embedding",
            "fine-tune",
            "fine tuning",
            "llm",
            "vector",
            "dataset",
            "학습",
            "모델",
            "인공지능",
        ],
        "data-engineer": [
            "etl",
            "elt",
            "data pipeline",
            "data lake",
            "data warehouse",
            "airflow",
            "dbt",
            "spark",
            "kafka",
            "flink",
            "schema",
            "데이터 파이프라인",
            "데이터 레이크",
        ],
        "embedded-coder": [
            "embedded",
            "firmware",
            "mcu",
            "rtos",
            "freertos",
            "bare metal",
            "interrupt",
            "gpio",
            "uart",
            "spi",
            "i2c",
            "watchdog",
            "임베디드",
            "펌웨어",
            ".c",
            ".h",
        ],
        "devops-engineer": [
            "ci",
            "cd",
            "ci/cd",
            "pipeline",
            "docker",
            "kubernetes",
            "k8s",
            "helm",
            "terraform",
            "deploy",
            "deployment",
            "release",
            "infra",
            "infrastructure",
            "배포",
            "인프라",
        ],
        "cloud-architect": [
            "cloud",
            "aws",
            "gcp",
            "azure",
            "architecture",
            "vpc",
            "iac",
            "cost optimization",
            "autoscaling",
            "serverless",
            "클라우드",
            "아키텍처",
        ],
        "network-engineer": [
            "network",
            "vlan",
            "routing",
            "firewall",
            "acl",
            "bgp",
            "ospf",
            "vpn",
            "dns",
            "load balancer",
            "cisco",
            "juniper",
            "네트워크",
            "방화벽",
            "라우팅",
        ],
        "dba": [
            "migration",
            "index",
            "query optimization",
            "schema design",
            "sql",
            "postgres",
            "postgresql",
            "mysql",
            "mariadb",
            "mongodb",
            "slow query",
            "마이그레이션",
            "인덱스",
            "쿼리 최적화",
        ],
        "test-harness-engineer": [
            "test harness",
            "test infrastructure",
            "fixture",
            "factory",
            "test framework",
            "test setup",
            "테스트 하네스",
            "테스트 인프라",
        ],
        "performance-engineer": [
            "performance",
            "load test",
            "stress test",
            "benchmark",
            "profiling",
            "latency",
            "throughput",
            "bottleneck",
            "성능",
            "부하 테스트",
            "프로파일링",
        ],
        "security-engineer": [
            "security",
            "vulnerability",
            "cve",
            "owasp",
            "pentest",
            "penetration",
            "exploit",
            "audit",
            "threat",
            "injection",
            "xss",
            "csrf",
            "보안",
            "취약점",
            "침투 테스트",
        ],
    }

    for role, keywords in role_keywords.items():
        if role not in configured:
            continue
        score = 0
        for keyword in keywords:
            if keyword in normalized:
                score += 1
        if score:
            scored[role] = score

    if scored:
        return max(scored.items(), key=lambda item: item[1])[0]
    return default_intake_role(cfg)


def next_agent_name(pool: dict[str, Any], role: str) -> str:
    pattern = re.compile(rf"^{re.escape(role)}-(\d+)$")
    seen = {int(m.group(1)) for agent in pool["agents"] if (m := pattern.match(agent["name"]))}
    idx = 1
    while idx in seen:
        idx += 1
    return f"{role}-{idx}"


def mux_has_session(mux: str, name: str) -> bool:
    result = subprocess.run([mux, "has-session", "-t", name], text=True, capture_output=True)
    return result.returncode == 0


def mux_window_exists(mux: str, session: str, window_name: str) -> bool:
    result = subprocess.run([mux, "list-windows", "-t", session, "-F", "#W"], text=True, capture_output=True)
    if result.returncode != 0:
        return False
    return window_name in result.stdout.splitlines()


def mux_new_session(mux: str, session: str, window_name: str, command: str, cwd: Path) -> None:
    run([mux, "new-session", "-d", "-s", session, "-n", window_name, "-c", str(cwd), command])


def mux_new_window(mux: str, session: str, window_name: str, command: str, cwd: Path) -> None:
    run([mux, "new-window", "-t", session, "-n", window_name, "-c", str(cwd), command])


def mux_kill_window(mux: str, session: str, window_name: str) -> None:
    subprocess.run([mux, "kill-window", "-t", f"{session}:{window_name}"], text=True)


def mux_select_window(mux: str, session: str, window_name: str) -> None:
    subprocess.run([mux, "select-window", "-t", f"{session}:{window_name}"], text=True)


def mux_attach(mux: str, session: str) -> None:
    os.execvp(mux, [mux, "attach-session", "-t", session])


def create_task(
    project_dir: Path,
    role: str,
    text: str,
    *,
    created_by: str = "leader",
    priority: str = "normal",
    scope: str = "task",
    paths: list[str] | None = None,
    depends_on: list[str] | None = None,
    parent_task_id: str | None = None,
    root_task_id: str | None = None,
    policy: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    cfg = ensure_project(project_dir)
    tasks, pool = load_state(project_dir, cfg)
    task_id = f"{role}-{uuid.uuid4().hex[:8]}"
    normalized = normalize_task(
        {
            "id": task_id,
            "role": role,
            "title": text.strip(),
            "status": "pending",
            "priority": priority,
            "scope": scope,
            "paths": list(paths or []),
            "depends_on": list(depends_on or []),
            "created_by": created_by,
            "parent_task_id": parent_task_id,
            "root_task_id": root_task_id or parent_task_id or task_id,
            "policy": policy
            or {
                "auto_review": role.endswith("-coder") or role == "coder",
                "auto_qa": role.endswith("-coder") or role == "coder",
                "auto_docs": contains_doc_hint(text),
            },
            "metadata": metadata or {},
        }
    )
    tasks["tasks"].append(normalized)
    if parent_task_id:
        parent = task_by_id(tasks, parent_task_id)
        if parent is not None:
            parent.setdefault("followups", [])
            parent["followups"].append(task_id)
            parent["updated_at"] = now_iso()
    save_state(project_dir, cfg, tasks, pool)
    return task_id


def enqueue_task_cli(
    project_dir: Path,
    role: str,
    text: str,
    *,
    created_by: str = "leader",
    priority: str = "normal",
    scope: str = "task",
) -> str:
    return create_task(
        project_dir,
        role,
        text,
        created_by=created_by,
        priority=priority,
        scope=scope,
    )


def summarize_status(project_dir: Path) -> str:
    cfg = ensure_project(project_dir)
    tasks, pool = load_state(project_dir, cfg)
    counts: dict[str, int] = {}
    for task in tasks["tasks"]:
        counts[task["status"]] = counts.get(task["status"], 0) + 1
    active_agents = ", ".join(f"{item['name']}({item['status']})" for item in pool["agents"]) or "none"
    task_summary = ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "no tasks"
    base_cap, effective_cap, burst_mode = compute_spawn_cap(cfg, tasks)
    total_running = sum(1 for a in pool["agents"] if a.get("role") != "leader")
    cap_note = f"cap={effective_cap}/8 (burst)" if burst_mode else f"cap={effective_cap}/8"
    return f"tasks: {task_summary}\nagents: {active_agents}\nspawn: running={total_running}, {cap_note}"


def leader_runtime_instructions(project_dir: Path) -> str:
    runtime = runtime_home()
    runtime_py = runtime / "lib" / "runtime.py"
    project = str(project_dir)
    return "\n".join(
        [
            "Runtime commands:",
            f"- Queue a task: python3 {runtime_py} enqueue --project-dir {shlex.quote(project)} --role <role> --text '<task>'",
            f"- Show status: python3 {runtime_py} status --project-dir {shlex.quote(project)}",
            f"- Spawn explicitly: bash {runtime / 'scripts' / 'spawn.sh'} {shlex.quote(project)} <role>",
            "",
            "Working rules:",
            "- Act as the conductor. Do not implement production code directly unless the user explicitly asks you to stop orchestrating.",
            "- Convert user requests into concrete role-specific tasks and enqueue them through the runtime commands above.",
            "- Prefer the most specific specialist role available: product-manager for requirements/PRD, ux-designer for UX flows, backend-coder for API/server logic, frontend-coder for UI, mobile-coder for iOS/Android, desktop-coder for Tauri/native, embedded-coder for firmware/MCU, crawler-coder for scraping/automation, ai-ml-engineer for ML/model work, data-engineer for ETL/pipelines, devops-engineer for CI/CD/containers, cloud-architect for cloud design, network-engineer for networking/firewall, dba for schema/migrations/query tuning, test-harness-engineer for test infra, performance-engineer for load/benchmarks, security-engineer for audits/vulnerabilities, reviewer for code review, qa for verification, docs-writer for documentation.",
            "- Use status checks to understand queue pressure before launching more work.",
        ]
    )


def upsert_agent(pool: dict[str, Any], payload: dict[str, Any]) -> None:
    for idx, agent in enumerate(pool["agents"]):
        if agent["name"] == payload["name"]:
            pool["agents"][idx] = payload
            return
    pool["agents"].append(payload)


def count_role_agents(pool: dict[str, Any], role: str) -> int:
    return sum(1 for agent in pool["agents"] if agent["role"] == role)


def oldest_idle_agents(pool: dict[str, Any], role: str) -> list[dict[str, Any]]:
    idle_agents = [agent for agent in pool["agents"] if agent["role"] == role and agent.get("status") == "idle"]
    return sorted(idle_agents, key=lambda agent: agent.get("idle_since") or agent.get("started_at") or "")


def remove_agent(pool: dict[str, Any], agent_name: str) -> None:
    pool["agents"] = [agent for agent in pool["agents"] if agent["name"] != agent_name]


def claim_task(tasks: dict[str, Any], role: str) -> dict[str, Any] | None:
    completed = {t["id"] for t in tasks["tasks"] if t["status"] in {"done", "reviewed", "failed"}}
    for task in tasks["tasks"]:
        if task["role"] == role and task["status"] == "pending":
            deps = task.get("depends_on", [])
            if not all(dep in completed for dep in deps):
                continue
            task["status"] = "running"
            task["started_at"] = now_iso()
            task["updated_at"] = now_iso()
            task["attempts"] = int(task.get("attempts", 0)) + 1
            return task
    return None


def assign_task(tasks: dict[str, Any], task_id: str, agent_name: str) -> dict[str, Any] | None:
    for task in tasks["tasks"]:
        if task["id"] == task_id:
            task["status"] = "running"
            task["agent"] = agent_name
            task["started_at"] = now_iso()
            task["updated_at"] = now_iso()
            task["attempts"] = int(task.get("attempts", 0)) + 1
            return task
    return None


def task_by_id(tasks: dict[str, Any], task_id: str | None) -> dict[str, Any] | None:
    if not task_id:
        return None
    for task in tasks["tasks"]:
        if task["id"] == task_id:
            return task
    return None


def open_followup_exists(tasks: dict[str, Any], parent_task_id: str, role: str, reason: str) -> bool:
    for task in tasks["tasks"]:
        if task.get("parent_task_id") != parent_task_id:
            continue
        if task.get("role") != role:
            continue
        if task.get("metadata", {}).get("reason") != reason:
            continue
        if task.get("status") not in {"done", "reviewed", "failed"}:
            return True
    return False


def append_artifact(task: dict[str, Any], artifact_path: Path) -> None:
    value = str(artifact_path)
    artifacts = task.setdefault("artifacts", [])
    if value not in artifacts:
        artifacts.append(value)


def finish_task(
    tasks: dict[str, Any],
    task_id: str,
    role: str,
    status_override: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    for task in tasks["tasks"]:
        if task["id"] == task_id:
            if status_override:
                task["status"] = status_override
            elif role.endswith("-coder") or role == "coder":
                task["status"] = "done"
            else:
                task["status"] = "reviewed"
            task["completed_at"] = now_iso()
            task["result"] = result
            if result and result.get("error"):
                task["last_error"] = result["error"]
            task["updated_at"] = now_iso()
            return


def clean_missing_windows(project_dir: Path, pool: dict[str, Any]) -> None:
    mux = detect_mux()
    session = session_name(project_dir)
    existing = []
    for agent in pool["agents"]:
        if mux_window_exists(mux, session, agent["name"]):
            existing.append(agent)
    pool["agents"] = existing


def refresh_agent_states(tasks: dict[str, Any], pool: dict[str, Any]) -> None:
    changed_at = now_iso()
    for agent in pool["agents"]:
        task = task_by_id(tasks, agent.get("task_id"))
        if task and task.get("status") == "running":
            agent["status"] = "busy"
            agent.pop("idle_since", None)
            continue
        if agent.get("status") != "idle":
            agent["status"] = "idle"
            agent["idle_since"] = changed_at
        elif not agent.get("idle_since"):
            agent["idle_since"] = changed_at


def write_task_artifact(
    project_dir: Path,
    cfg: Config,
    task: dict[str, Any] | None,
    agent_name: str,
    role: str,
    exit_code: int,
    prompt_file: Path,
    note: str,
) -> Path:
    paths = project_paths(project_dir, cfg)
    ensure_dir(paths["outputs_dir"])
    task_id = task["id"] if task else f"{role}-{uuid.uuid4().hex[:8]}"
    artifact_path = paths["outputs_dir"] / f"{task_id}.md"
    lines = [
        f"# Task Result: {task_id}",
        "",
        f"- role: {role}",
        f"- agent: {agent_name}",
        f"- exit_code: {exit_code}",
        f"- status: {'success' if exit_code == 0 else 'failed'}",
        f"- generated_at: {now_iso()}",
        f"- prompt_file: {prompt_file}",
    ]
    if task:
        lines += [
            f"- title: {task['title']}",
            f"- root_task_id: {task.get('root_task_id')}",
            f"- parent_task_id: {task.get('parent_task_id')}",
        ]
    lines += ["", "## Summary", "", note.strip() or "No summary provided.", ""]

    if task:
        mape_k = task.get("mape_k", {})
        if mape_k:
            lines += ["", "## MAPE-K", "", "| Stage | At | Notes |", "|-------|-----|-------|"]
            for stage in ("monitor", "analyze", "plan", "execute", "verify", "knowledge"):
                for entry in mape_k.get(stage, []):
                    at = entry.get("at", "")
                    notes = str({k: v for k, v in entry.items() if k != "at"})[:120]
                    lines.append(f"| {stage} | {at} | {notes} |")
            lines.append("")

        impact = task.get("impact", {})
        if impact:
            lines += [
                "## Impact",
                "",
                f"- Changed files: {impact.get('changed_files', 'n/a')}",
                f"- Diff stat: {(impact.get('diff_stat') or '').splitlines()[0] if impact.get('diff_stat') else 'n/a'}",
                f"- Duration: {impact.get('duration_secs', 0)}s",
                "",
            ]

        review = task.get("review", {})
        if review:
            lines += [
                "## Review",
                "",
                f"- Status: {review.get('status', 'none')}",
                f"- Attempts: {review.get('attempts', 0)}",
                "",
            ]

    write_text(artifact_path, "\n".join(lines))
    return artifact_path


def enqueue_followup_tasks(project_dir: Path, cfg: Config, tasks: dict[str, Any], task: dict[str, Any]) -> None:
    role = task["role"]
    policy = task.get("policy", {})
    title = task["title"]
    configured_roles = {str(item.get("name")) for item in cfg.agents}

    if (role.endswith("-coder") or role == "coder") and task["status"] == "done":
        if policy.get("auto_review") and "reviewer" in configured_roles:
            if not open_followup_exists(tasks, task["id"], "reviewer", "auto_review"):
                create_task(
                    project_dir,
                    "reviewer",
                    f"Review completed implementation: {title}",
                    created_by="system",
                    priority=task.get("priority", "normal"),
                    scope="review",
                    paths=task.get("paths", []),
                    depends_on=[task["id"]],
                    parent_task_id=task["id"],
                    root_task_id=task.get("root_task_id"),
                    policy={"auto_review": False, "auto_qa": False, "auto_docs": False},
                    metadata={"reason": "auto_review", "source_task_id": task["id"]},
                )
        if policy.get("auto_docs") and "docs-writer" in configured_roles:
            if not open_followup_exists(tasks, task["id"], "docs-writer", "auto_docs"):
                docs_task_text = f"Update docs for completed implementation: {title}"
                if cfg.docs.get("wiki_llm"):
                    wiki_dir = cfg.docs.get("wiki_dir", "wiki-llm")
                    docs_task_text += (
                        f"\n완료 후 {wiki_dir}/wiki/ 해당 feature 페이지를 업데이트하고"
                        f" index.md/log.md를 갱신하라. 포맷은 {wiki_dir}/CLAUDE.md 규칙을 따른다."
                    )
                create_task(
                    project_dir,
                    "docs-writer",
                    docs_task_text,
                    created_by="system",
                    priority=task.get("priority", "normal"),
                    scope="docs",
                    paths=task.get("paths", []),
                    depends_on=[task["id"]],
                    parent_task_id=task["id"],
                    root_task_id=task.get("root_task_id"),
                    policy={"auto_review": False, "auto_qa": False, "auto_docs": False},
                    metadata={"reason": "auto_docs", "source_task_id": task["id"]},
                )

    if role == "reviewer" and task["status"] == "reviewed":
        source_task_id = task.get("metadata", {}).get("source_task_id") or task.get("parent_task_id")
        source_task = task_by_id(tasks, source_task_id)
        if not source_task:
            return
        if source_task.get("policy", {}).get("auto_qa") and "qa" in configured_roles:
            if not open_followup_exists(tasks, task["id"], "qa", "auto_qa"):
                create_task(
                    project_dir,
                    "qa",
                    f"Verify reviewed implementation: {source_task['title']}",
                    created_by="system",
                    priority=source_task.get("priority", "normal"),
                    scope="qa",
                    paths=source_task.get("paths", []),
                    depends_on=[task["id"]],
                    parent_task_id=task["id"],
                    root_task_id=source_task.get("root_task_id"),
                    policy={"auto_review": False, "auto_qa": False, "auto_docs": False},
                    metadata={"reason": "auto_qa", "source_task_id": source_task["id"]},
                )


def enqueue_workflow(project_dir: Path, workflow_name: str, task_description: str) -> list[str]:
    """Create all workflow stages as tasks with proper depends_on links."""
    wf_path = runtime_home() / "workflows" / f"{workflow_name}.json"
    if not wf_path.exists():
        src_path = workflows_root() / f"{workflow_name}.json"
        if src_path.exists():
            wf_path = src_path
        else:
            raise SystemExit(f"Workflow not found: {workflow_name}  (looked in {runtime_home() / 'workflows'})")

    workflow = load_json(wf_path, {})
    stages = workflow.get("stages", [])
    if not stages:
        raise SystemExit(f"Workflow '{workflow_name}' has no stages.")

    stage_to_task: dict[str, str] = {}
    task_ids: list[str] = []
    root_task_id: str | None = None

    for stage in stages:
        stage_id = stage["id"]
        role = stage["role"]
        title_tpl = stage.get("title_template", "{task}")
        title = title_tpl.replace("{task}", task_description)
        scope = stage.get("scope", "task")
        policy = stage.get("policy")
        extra_meta = stage.get("metadata", {})

        dep_stage_ids = stage.get("depends_on", [])
        dep_task_ids = [stage_to_task[sid] for sid in dep_stage_ids if sid in stage_to_task]

        task_id = create_task(
            project_dir,
            role,
            title,
            created_by="workflow",
            scope=scope,
            depends_on=dep_task_ids,
            root_task_id=root_task_id,
            policy=policy,
            metadata={**extra_meta, "workflow": workflow_name, "stage": stage_id},
        )
        stage_to_task[stage_id] = task_id
        task_ids.append(task_id)
        if root_task_id is None:
            root_task_id = task_id

    return task_ids


def spawn_agent(project_dir: Path, role: str, agent_name: str | None, task_id: str | None) -> str:
    cfg = ensure_project(project_dir)
    tasks, pool = load_state(project_dir, cfg)
    clean_missing_windows(project_dir, pool)

    role_cfg = find_agent_cfg(cfg, role)
    if role_cfg is None:
        raise SystemExit(f"Role not configured: {role}")

    name = agent_name or next_agent_name(pool, role)
    session = session_name(project_dir)
    mux = detect_mux()

    if task_id:
        task = assign_task(tasks, task_id, name)
        if task is None:
            raise SystemExit(f"Task not found: {task_id}")
    else:
        task = claim_task(tasks, role)
        if task is not None:
            task["agent"] = name
            task["updated_at"] = now_iso()

    upsert_agent(
        pool,
        {
            "name": name,
            "role": role,
            "status": "busy" if task else "idle",
            "task_id": task["id"] if task else None,
            "started_at": now_iso(),
            "idle_since": None if task else now_iso(),
        },
    )
    save_state(project_dir, cfg, tasks, pool)

    runtime = runtime_home()
    cmd = [
        "python3",
        str(runtime / "lib" / "runtime.py"),
        "run-agent",
        "--project-dir",
        str(project_dir),
        "--role",
        role,
        "--agent-name",
        name,
    ]
    if task:
        cmd += ["--task-id", task["id"]]
    window_command = shell_join(cmd)

    if mux_window_exists(mux, session, name):
        raise SystemExit(f"Window already exists: {name}")

    mux_new_window(mux, session, name, window_command, project_dir)
    return name


def kill_agent(project_dir: Path, agent_name: str) -> None:
    cfg = ensure_project(project_dir)
    tasks, pool = load_state(project_dir, cfg)
    mux = detect_mux()
    session = session_name(project_dir)
    mux_kill_window(mux, session, agent_name)
    remove_agent(pool, agent_name)
    save_state(project_dir, cfg, tasks, pool)


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path, ignore_errors=True)


def clean(project_dir: Path) -> None:
    session = session_name(project_dir)
    if command_exists("tmux") and mux_has_session("tmux", session):
        subprocess.run(["tmux", "kill-session", "-t", session], check=False, text=True, capture_output=True)

    cfg = ensure_project(project_dir)
    paths = project_paths(project_dir, cfg)
    targets = [
        project_dir / ".ai-state",
        paths["tasks_file"].parent,
        paths["outputs_dir"],
    ]
    for path in targets:
        remove_path(path)

    rt_home = runtime_home()
    local_bin = Path.home() / ".local" / "bin"
    for name in ["ai-start", "ai-init", "ai-clean", "teamstart", "teaminit", "teamclean", "teamupdate"]:
        remove_path(local_bin / name)
    remove_path(rt_home)

    print(f"cleaned runtime install and project state for {project_dir}")


def setup(repo_root: Path, project_dir: Path) -> None:
    rt_home = runtime_home()
    ensure_dir(rt_home)
    for name in ["bin", "scripts", "prompts", "templates", "lib"]:
        ensure_dir(rt_home / name)

    mapping = {
        repo_root / "runtime" / "bin" / "teamstart": rt_home / "bin" / "teamstart",
        repo_root / "runtime" / "bin" / "teaminit": rt_home / "bin" / "teaminit",
        repo_root / "runtime" / "bin" / "teamclean": rt_home / "bin" / "teamclean",
        repo_root / "runtime" / "bin" / "teamupdate": rt_home / "bin" / "teamupdate",
        repo_root / "runtime" / "scripts" / "spawn.sh": rt_home / "scripts" / "spawn.sh",
        repo_root / "runtime" / "scripts" / "kill.sh": rt_home / "scripts" / "kill.sh",
        repo_root / "runtime" / "scripts" / "watcher.sh": rt_home / "scripts" / "watcher.sh",
        repo_root / "runtime" / "scripts" / "leader.sh": rt_home / "scripts" / "leader.sh",
        repo_root / "runtime" / "lib" / "runtime.py": rt_home / "lib" / "runtime.py",
    }

    for src, dest in mapping.items():
        if dest.exists() or dest.is_symlink():
            dest.unlink()
        dest.symlink_to(src)

    copy_dirs = {
        "prompts": repo_root / "runtime" / "prompts",
        "templates": repo_root / "templates",
        "skills": repo_root / "runtime" / "skills",
        "workflows": repo_root / "runtime" / "workflows",
        "hooks": repo_root / "runtime" / "hooks",
    }
    for dest_name, src_dir in copy_dirs.items():
        if not src_dir.exists():
            continue
        dest_dir = rt_home / dest_name
        if dest_dir.exists() or dest_dir.is_symlink():
            shutil.rmtree(dest_dir, ignore_errors=True)
        shutil.copytree(src_dir, dest_dir)

    local_bin = Path.home() / ".local" / "bin"
    ensure_dir(local_bin)
    for name in ["teamstart", "teaminit", "teamclean", "teamupdate"]:
        link = local_bin / name
        target = rt_home / "bin" / name
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(target)

    ensure_project(project_dir)

    installed = install_skills()
    if installed:
        print(f"skills installed: {', '.join(installed)}")

    path_hint = str(local_bin)
    print(f"runtime installed at {rt_home}")
    print(f"project initialized at {project_dir}")
    print(f"ensure {path_hint} is on PATH")


def start(project_dir: Path) -> None:
    is_first_run = not (project_dir / ".ai-config.yaml").exists()
    if is_first_run:
        cmd_wizard(project_dir)
        if not _confirm("\n  tmux 세션을 지금 시작할까요?", default=True):
            return
    else:
        ensure_project(project_dir)
    mux = detect_mux()
    session = session_name(project_dir)
    runtime = runtime_home()
    leader_cmd = shell_join(["bash", str(runtime / "scripts" / "leader.sh"), str(project_dir)])
    watcher_cmd = shell_join(["bash", str(runtime / "scripts" / "watcher.sh"), str(project_dir)])

    if not mux_has_session(mux, session):
        mux_new_session(mux, session, "leader", leader_cmd, project_dir)
        mux_new_window(mux, session, "watcher", watcher_cmd, project_dir)
    else:
        if not mux_window_exists(mux, session, "leader"):
            mux_new_window(mux, session, "leader", leader_cmd, project_dir)
        if not mux_window_exists(mux, session, "watcher"):
            mux_new_window(mux, session, "watcher", watcher_cmd, project_dir)

    mux_select_window(mux, session, "leader")
    print(f"starting session {session} with {mux}")
    mux_attach(mux, session)


def leader_session(project_dir: Path) -> int:
    ensure_project(project_dir)
    prompt = merge_prompt(project_dir, "leader")
    extra = leader_runtime_instructions(project_dir)
    system_prompt = f"{prompt}\n\n{extra}".strip()

    if not claude_available(project_dir):
        print("Claude CLI is not available for the leader session. Falling back to manual leader loop.")
        leader_loop(project_dir)
        return 0

    cmd = [
        "claude",
        "--dangerously-skip-permissions",
        "--append-system-prompt",
        system_prompt,
        "-n",
        "leader",
        "You are the leader agent for this project. Accept the user's requests in this session and orchestrate the worker runtime through the provided queue commands.",
    ]
    return subprocess.run(cmd, cwd=project_dir).returncode


def leader_loop(project_dir: Path) -> None:
    cfg = ensure_project(project_dir)
    print("leader ready")
    print("plain text => auto-routed specialist task")
    print("/review <text> => reviewer task")
    print("/qa <text> => qa task")
    print("/docs <text> => docs-writer task")
    print("/spawn <role> [text] => enqueue a task for a specific role")
    print("/workflow <name> <description> => enqueue full workflow pipeline")
    print("  workflows: standard | codex")
    print("/lesson [role] | <title> | <detail> => record a lesson to prevent recurrence")
    print("/lessons [role] => list recorded lessons")
    print("/status => show runtime state")
    print("/quit => exit leader loop")

    while True:
        try:
            line = input("leader> ").strip()
        except EOFError:
            print()
            return
        except KeyboardInterrupt:
            print()
            return

        if not line:
            continue
        if line in {"/quit", "quit", "exit"}:
            return
        if line == "/status":
            print(summarize_status(project_dir))
            continue
        if line.startswith("/review "):
            task_id = create_task(project_dir, "reviewer", line[len("/review ") :])
            print(f"queued reviewer task {task_id}")
            continue
        if line.startswith("/qa "):
            task_id = create_task(project_dir, "qa", line[len("/qa ") :])
            print(f"queued qa task {task_id}")
            continue
        if line.startswith("/docs "):
            task_id = create_task(project_dir, "docs-writer", line[len("/docs ") :])
            print(f"queued docs task {task_id}")
            continue
        if line.startswith("/spawn "):
            payload = line[len("/spawn ") :].strip()
            if " " in payload:
                role, text = payload.split(" ", 1)
            else:
                role, text = payload, payload
            task_id = create_task(project_dir, role, text)
            print(f"queued {role} task {task_id}")
            continue
        if line.startswith("/workflow "):
            payload = line[len("/workflow ") :].strip()
            if " " in payload:
                wf_name, wf_desc = payload.split(" ", 1)
            else:
                wf_name, wf_desc = payload, payload
            try:
                wf_task_ids = enqueue_workflow(project_dir, wf_name, wf_desc)
                print(f"workflow '{wf_name}' enqueued: {len(wf_task_ids)} stages")
                for wf_tid in wf_task_ids:
                    print(f"  {wf_tid}")
            except SystemExit as exc:
                print(f"error: {exc}")
            continue
        if line.startswith("/lesson "):
            # format: /lesson [role] | <title> | <detail>
            # role is optional: /lesson backend-coder | title | detail
            #                   /lesson | title | detail   (all roles)
            parts = [p.strip() for p in line[len("/lesson "):].split("|")]
            if len(parts) == 3:
                lesson_role: str | None = parts[0] or None
                lesson_title, lesson_detail = parts[1], parts[2]
            elif len(parts) == 2:
                lesson_role = None
                lesson_title, lesson_detail = parts[0], parts[1]
            else:
                print("usage: /lesson [role] | <title> | <detail>")
                continue
            lid = record_lesson(project_dir, lesson_role, lesson_title, lesson_detail)
            print(f"lesson recorded: {lid}")
            continue
        if line.startswith("/lessons"):
            parts = line.split()
            filter_role = parts[1] if len(parts) > 1 else None
            print(list_lessons_text(project_dir, filter_role))
            continue
        role = infer_role_from_text(cfg, line)
        task_id = create_task(project_dir, role, line)
        print(f"queued {role} task {task_id}")


def compute_spawn_cap(cfg: Config, tasks: dict[str, Any]) -> tuple[int, int, bool]:
    """Return (base_cap, effective_cap, burst_mode).

    base_cap    = floor(auto_roles × 0.5), clamped [1, 8]
    burst_cap   = floor(auto_roles × 0.75), clamped [1, 8]  — when 3+ high-priority pending
    effective_cap = burst_cap if burst_mode else base_cap
    Absolute hard limit is always 8.
    """
    auto_roles = [a for a in cfg.agents if a.get("name") != "leader" and a.get("scale") == "auto"]
    n = len(auto_roles)
    base_cap = max(1, min(8, int(n * 0.5)))
    high_pending = sum(
        1 for t in tasks["tasks"]
        if t["status"] == "pending" and t.get("priority") == "high"
    )
    burst_mode = high_pending >= 3
    effective_cap = max(1, min(8, int(n * 0.75))) if burst_mode else base_cap
    return base_cap, effective_cap, burst_mode


def watch(project_dir: Path) -> None:
    cfg = ensure_project(project_dir)
    poll_seconds = int(os.environ.get("AI_WATCH_INTERVAL", "5"))
    idle_ttl_seconds = int(os.environ.get("AI_IDLE_TTL_SECONDS", "120"))
    _burst_notified = False
    print(f"watcher ready for {project_dir}")
    print(f"claude available: {'yes' if claude_available(project_dir) else 'no'}")

    while True:
        tasks, pool = load_state(project_dir, cfg)
        clean_missing_windows(project_dir, pool)
        refresh_agent_states(tasks, pool)

        pending_by_role: dict[str, int] = {}
        running_by_role: dict[str, int] = {}
        for task in tasks["tasks"]:
            if task["status"] == "pending":
                pending_by_role[task["role"]] = pending_by_role.get(task["role"], 0) + 1
        for agent in pool["agents"]:
            running_by_role[agent["role"]] = running_by_role.get(agent["role"], 0) + 1

        # --- global spawn cap (rolling + burst) ---
        base_cap, effective_cap, burst_mode = compute_spawn_cap(cfg, tasks)
        total_running = sum(1 for a in pool["agents"] if a.get("role") != "leader")
        if burst_mode and not _burst_notified:
            high_n = sum(1 for t in tasks["tasks"] if t["status"] == "pending" and t.get("priority") == "high")
            print(
                f"[spawn-cap] BURST: {high_n} high-priority tasks pending"
                f" — cap raised {base_cap}→{effective_cap} (max 8)"
            )
            _burst_notified = True
        elif not burst_mode:
            _burst_notified = False

        changed = False
        for role_cfg in cfg.agents:
            role = role_cfg.get("name")
            if role in {"leader"}:
                continue
            if role_cfg.get("scale") != "auto":
                continue
            minimum = int(role_cfg.get("min", 0))
            maximum = int(role_cfg.get("max", 1))
            desired = min(maximum, max(minimum, pending_by_role.get(role, 0)))
            running = running_by_role.get(role, 0)
            while running < desired:
                if total_running >= 8:
                    break
                if total_running >= effective_cap:
                    break
                min_free_mb = int(cfg.limits.get("min_free_memory_mb", 0))
                if min_free_mb > 0:
                    free_mb = get_free_memory_mb()
                    if free_mb is not None and free_mb < min_free_mb:
                        print(f"memory low: {free_mb}MB free < {min_free_mb}MB required, skipping spawn for {role}")
                        break
                name = spawn_agent(project_dir, role, None, None)
                print(f"spawned {name} (running={total_running + 1}/{effective_cap})")
                running += 1
                total_running += 1
                changed = True
            if running > desired:
                now_dt = datetime.now(timezone.utc)
                for agent in oldest_idle_agents(pool, str(role)):
                    if running <= desired:
                        break
                    idle_since = parse_iso(agent.get("idle_since"))
                    if idle_since is None:
                        continue
                    idle_seconds = (now_dt - idle_since).total_seconds()
                    if idle_seconds < idle_ttl_seconds:
                        continue
                    print(f"scaled down {agent['name']} after {int(idle_seconds)}s idle")
                    kill_agent(project_dir, agent["name"])
                    tasks, pool = load_state(project_dir, cfg)
                    refresh_agent_states(tasks, pool)
                    running = count_role_agents(pool, str(role))
                    changed = True

        if changed:
            tasks, pool = load_state(project_dir, cfg)
        save_state(project_dir, cfg, tasks, pool)
        time.sleep(poll_seconds)


# ---------------------------------------------------------------------------
# MAPE-K scaffolding
# ---------------------------------------------------------------------------

def mape_k_init(task: dict[str, Any]) -> None:
    task.setdefault("mape_k", {"monitor": [], "analyze": [], "plan": [], "execute": [], "verify": [], "knowledge": []})
    task.setdefault("impact", {})
    task.setdefault("review", {"status": "none", "attempts": 0})
    task.setdefault("verify_attempts", 0)
    task.setdefault("review_attempts", 0)


def mape_k_record(task: dict[str, Any], stage: str, payload: dict[str, Any]) -> None:
    entry = {"at": now_iso(), **payload}
    task.setdefault("mape_k", {}).setdefault(stage, []).append(entry)


# ---------------------------------------------------------------------------
# Impact loop helpers
# ---------------------------------------------------------------------------

def _run_git(project_dir: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(project_dir)] + args,
            capture_output=True, text=True, timeout=15,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def capture_pre_snapshot(project_dir: Path, task: dict[str, Any]) -> dict[str, Any]:
    head = _run_git(project_dir, ["rev-parse", "HEAD"])
    dirty = _run_git(project_dir, ["status", "--porcelain"])
    snap = {"head": head, "dirty_files": len([ln for ln in dirty.splitlines() if ln.strip()]), "at": now_iso()}
    task.setdefault("impact", {})["pre"] = snap
    return snap


def capture_post_snapshot(project_dir: Path, task: dict[str, Any]) -> dict[str, Any]:
    head = _run_git(project_dir, ["rev-parse", "HEAD"])
    dirty = _run_git(project_dir, ["status", "--porcelain"])
    snap = {"head": head, "dirty_files": len([ln for ln in dirty.splitlines() if ln.strip()]), "at": now_iso()}
    task.setdefault("impact", {})["post"] = snap
    return snap


def compute_impact(project_dir: Path, task: dict[str, Any], pre: dict[str, Any], post: dict[str, Any]) -> None:
    diff_stat = _run_git(project_dir, ["diff", "--stat", pre.get("head", "HEAD~1"), post.get("head", "HEAD")])
    changed_files = len([ln for ln in diff_stat.splitlines() if "|" in ln])
    try:
        from datetime import datetime
        pre_dt = datetime.fromisoformat(pre["at"].replace("Z", "+00:00"))
        post_dt = datetime.fromisoformat(post["at"].replace("Z", "+00:00"))
        duration = int((post_dt - pre_dt).total_seconds())
    except Exception:
        duration = 0
    task["impact"].update({"diff_stat": diff_stat, "changed_files": changed_files, "duration_secs": duration})


# ---------------------------------------------------------------------------
# Harness verification loop
# ---------------------------------------------------------------------------

def run_verification_gate(
    project_dir: Path, cfg: Config, task: dict[str, Any], exit_code: int
) -> tuple[str, str]:
    if exit_code != 0:
        return ("fail", f"worker exited with code {exit_code}")
    verify_cfg = getattr(cfg, "verification", {}) or {}
    if not isinstance(verify_cfg, dict):
        verify_cfg = {}
    cmd_str = verify_cfg.get("command", "")
    if not cmd_str:
        return ("skipped", "no verification command configured")
    try:
        r = subprocess.run(cmd_str, shell=True, cwd=project_dir, capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            return ("pass", r.stdout.strip()[:500])
        return ("fail", (r.stdout + r.stderr).strip()[:500])
    except Exception as e:
        return ("fail", str(e))


def should_retry_harness(task: dict[str, Any], max_attempts: int) -> bool:
    return int(task.get("verify_attempts", 0)) < max_attempts


def mark_unverified(task: dict[str, Any], reason: str) -> None:
    task["status"] = "unverified"
    task["updated_at"] = now_iso()
    task.setdefault("review", {})["status"] = "unverified"
    task["review"]["reason"] = reason


# ---------------------------------------------------------------------------
# Adversarial review gate
# ---------------------------------------------------------------------------

def enter_review_gate(
    project_dir: Path, cfg: Config, tasks: dict[str, Any], task: dict[str, Any]
) -> None:
    task["status"] = "awaiting_review"
    task["updated_at"] = now_iso()
    task.setdefault("review", {})["status"] = "awaiting_review"
    configured_roles = {str(item.get("name")) for item in cfg.agents}
    if "reviewer" not in configured_roles:
        return
    if open_followup_exists(tasks, task["id"], "reviewer", "adversarial_review"):
        return
    create_task(
        project_dir,
        "reviewer",
        f"[Adversarial Review] {task['title']}",
        created_by="system",
        priority=task.get("priority", "normal"),
        scope="review",
        paths=task.get("paths", []),
        depends_on=[],
        parent_task_id=task["id"],
        root_task_id=task.get("root_task_id"),
        policy={"auto_review": False, "auto_qa": False, "auto_docs": False},
        metadata={"reason": "adversarial_review", "source_task_id": task["id"]},
    )


def parse_reviewer_verdict(artifact_path: Path) -> tuple[str, list[str]]:
    if not artifact_path.exists():
        return ("pending", ["artifact not found"])
    text = read_text(artifact_path)
    lower = text.lower()
    if "## verdict: approved" in lower:
        verdict = "approved"
    elif "## verdict: rejected" in lower:
        verdict = "rejected"
    else:
        verdict = "pending"
    reasons: list[str] = []
    for line in text.splitlines():
        ls = line.strip()
        if ls.startswith("- ") and verdict in ("rejected", "pending"):
            reasons.append(ls[2:])
    return (verdict, reasons[:10])


def apply_review_verdict(
    project_dir: Path,
    cfg: Config,
    tasks: dict[str, Any],
    reviewer_task: dict[str, Any],
    verdict: str,
    reasons: list[str],
) -> None:
    source_task_id = reviewer_task.get("metadata", {}).get("source_task_id") or reviewer_task.get("parent_task_id")
    source_task = task_by_id(tasks, source_task_id)

    if verdict == "approved":
        if source_task:
            source_task["status"] = "done"
            source_task["updated_at"] = now_iso()
            source_task.setdefault("review", {})["status"] = "approved"
        enqueue_followup_tasks(project_dir, cfg, tasks, source_task or reviewer_task)
        return

    review_attempts = int(reviewer_task.get("review_attempts", 0)) + 1
    reviewer_task["review_attempts"] = review_attempts
    max_rejections = int(os.environ.get("AI_REVIEW_MAX_REJECTIONS", "3"))

    if source_task:
        source_task.setdefault("review", {})["attempts"] = review_attempts
        source_task["review"]["status"] = "rejected"
        source_task["review"]["reasons"] = reasons

    if review_attempts <= max_rejections:
        src = source_task or reviewer_task
        create_task(
            project_dir,
            src.get("role", "backend-coder"),
            f"[Rework {review_attempts}/{max_rejections}] {src['title']}",
            created_by="system",
            priority="high",
            scope="implementation",
            paths=src.get("paths", []),
            depends_on=[],
            parent_task_id=source_task_id,
            root_task_id=src.get("root_task_id"),
            policy={"auto_review": False, "auto_qa": False, "auto_docs": False},
            metadata={
                "reason": "rework",
                "source_task_id": source_task_id,
                "rejection_reasons": reasons,
                "review_attempt": review_attempts,
            },
        )
    else:
        if source_task:
            source_task["status"] = "blocked"
            source_task["updated_at"] = now_iso()
        escalate_blocked(project_dir, source_task or reviewer_task)


def escalate_blocked(project_dir: Path, task: dict[str, Any]) -> None:
    task["status"] = "blocked"
    task["updated_at"] = now_iso()
    record_task_lesson(project_dir, task, "blocked")


# ---------------------------------------------------------------------------
# MAPE-K Analyze / Plan helpers
# ---------------------------------------------------------------------------

def analyze_task_context(tasks: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    return {
        "attempts": int(task.get("attempts", 0)),
        "verify_attempts": int(task.get("verify_attempts", 0)),
        "review_attempts": int(task.get("review_attempts", 0)),
        "rejection_reasons": task.get("review", {}).get("reasons", []),
        "total_pending": sum(1 for t in tasks["tasks"] if t["status"] == "pending"),
    }


def plan_task_execution(
    task: dict[str, Any], ctx: dict[str, Any], role: str, iteration: int
) -> list[str]:
    lines = [
        f"Role: {role}",
        f"Agent: {task.get('agent', 'unknown')}",
        f"Task ID: {task['id']}",
        f"Task: {task['title']}",
    ]
    if iteration > 1:
        lines.append(f"Iteration: {iteration}")
    if ctx.get("verify_attempts", 0) > 0:
        lines.append(f"Verify attempts so far: {ctx['verify_attempts']}")
    if ctx.get("rejection_reasons"):
        lines.append("Rejection reasons from previous review:")
        for r in ctx["rejection_reasons"]:
            lines.append(f"  - {r}")
    rework_meta = task.get("metadata", {})
    if rework_meta.get("reason") == "rework" and rework_meta.get("rejection_reasons"):
        lines.append("Required fixes (from reviewer):")
        for r in rework_meta["rejection_reasons"]:
            lines.append(f"  - {r}")
    return lines


# ---------------------------------------------------------------------------
# Knowledge: record lesson
# ---------------------------------------------------------------------------

def record_task_lesson(project_dir: Path, task: dict[str, Any], kind: str) -> None:
    titles = {
        "unverified": "Task failed harness verification",
        "blocked": "Task blocked after max review rejections",
        "rework": "Task required rework after review",
    }
    details = {
        "unverified": f"Task '{task['title']}' (id={task['id']}) failed automated harness verification after max attempts.",
        "blocked": f"Task '{task['title']}' (id={task['id']}) was blocked after exceeding max review rejections. Manual intervention required.",
        "rework": f"Task '{task['title']}' (id={task['id']}) was sent back for rework. Check rejection reasons in task metadata.",
    }
    title = titles.get(kind, f"Task {kind}")
    detail = details.get(kind, f"Task {task['id']} encountered {kind}")
    try:
        role = task.get("role", "unknown")
        subprocess.run(
            ["python3", str(runtime_home() / "lib" / "runtime.py"), "lesson",
             "--project-dir", str(project_dir), "--role", role,
             "--title", title, "--detail", detail],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass


def run_agent(project_dir: Path, role: str, agent_name: str, task_id: str | None) -> int:
    """Run an agent in a continuation loop.

    After each task the agent immediately claims the next pending task for the
    same role (follow-ups included) without exiting the tmux window.  When no
    task is available the agent polls up to AI_AGENT_IDLE_CHECKS times at
    AI_AGENT_IDLE_POLL-second intervals before giving up and exiting.

    Set AI_AGENT_LOOP=false to disable looping (single-task mode).
    """
    cfg = ensure_project(project_dir)
    loop_enabled = os.environ.get("AI_AGENT_LOOP", "true").lower() != "false"
    max_idle_checks = int(os.environ.get("AI_AGENT_IDLE_CHECKS", "6"))
    idle_poll_secs = int(os.environ.get("AI_AGENT_IDLE_POLL", "5"))

    idle_checks = 0
    last_exit_code = 0
    iteration = 0

    while True:
        iteration += 1
        tasks, pool = load_state(project_dir, cfg)
        task: dict[str, Any] | None = None

        # --- locate or claim task ---
        if task_id:
            task = task_by_id(tasks, task_id)
            if task is None:
                print(f"[{agent_name}] task {task_id} not found — stopping")
                break
            if task.get("status") == "pending":
                task["status"] = "running"
                task["agent"] = agent_name
                task["started_at"] = now_iso()
                task["updated_at"] = now_iso()
                task["attempts"] = int(task.get("attempts", 0)) + 1
                save_state(project_dir, cfg, tasks, pool)
        else:
            task = claim_task(tasks, role)
            if task is not None:
                task["agent"] = agent_name
                task["updated_at"] = now_iso()
                save_state(project_dir, cfg, tasks, pool)

        # --- no task available: idle-poll or exit ---
        if task is None:
            if not loop_enabled:
                break
            idle_checks += 1
            if idle_checks > max_idle_checks:
                print(f"[{agent_name}] no tasks after {max_idle_checks} checks — stopping")
                break
            print(f"[{agent_name}] idle {idle_checks}/{max_idle_checks}, next check in {idle_poll_secs}s")
            time.sleep(idle_poll_secs)
            task_id = None
            continue

        idle_checks = 0
        current_task_id = task["id"]
        max_harness = int(os.environ.get("AI_HARNESS_MAX_ATTEMPTS", "3"))
        enforce_review = bool(getattr(cfg, "review", {}) and (cfg.review if isinstance(getattr(cfg, "review", None), dict) else {}).get("enforce", False))  # type: ignore[attr-defined]

        # [M] Monitor
        mape_k_init(task)
        pre = capture_pre_snapshot(project_dir, task)
        mape_k_record(task, "monitor", {"pre_head": pre.get("head", ""), "dirty_files": pre.get("dirty_files", 0)})
        save_state(project_dir, cfg, tasks, pool)

        # [A] Analyze
        ctx = analyze_task_context(tasks, task)
        mape_k_record(task, "analyze", ctx)

        # [P→E→V] Harness loop
        prompt = merge_prompt(project_dir, role)
        prompt_file = project_dir / ".ai-state" / f"{agent_name}.prompt.txt"
        exit_code = 0
        summary_note = "Prompt prepared but no worker session was launched."
        verdict: str = "skipped"
        verify_details: str = ""

        while should_retry_harness(task, max_harness):
            task["verify_attempts"] = int(task.get("verify_attempts", 0)) + 1
            payload_lines = plan_task_execution(task, ctx, role, iteration)
            payload_lines_full = [f"Project: {cfg.project}"] + payload_lines
            write_text(prompt_file, prompt + "\n\n" + "\n".join(payload_lines_full) + "\n")
            mape_k_record(task, "plan", {"payload_lines": len(payload_lines_full), "verify_attempts": task["verify_attempts"]})
            save_state(project_dir, cfg, tasks, pool)

            print(f"[{agent_name}] starting role={role} iter={iteration} verify_attempt={task['verify_attempts']}")
            print(f"[{agent_name}] task={task['title']}")

            if claude_available(project_dir):
                cmd = [
                    "claude",
                    "--dangerously-skip-permissions",
                    "--append-system-prompt",
                    prompt,
                    "-n",
                    agent_name,
                    "\n".join(payload_lines_full),
                ]
                exit_code = subprocess.run(cmd, cwd=project_dir).returncode
                summary_note = "Worker session finished. Review the terminal transcript for the full interaction."
            else:
                print("Claude CLI or .claude config not available. Prompt prepared but no agent was launched.")

            mape_k_record(task, "execute", {"exit_code": exit_code})

            # reload task state after claude run
            tasks, pool = load_state(project_dir, cfg)
            task = task_by_id(tasks, current_task_id)
            if task is None:
                break

            verdict, verify_details = run_verification_gate(project_dir, cfg, task, exit_code)
            mape_k_record(task, "verify", {"verdict": verdict, "details": verify_details[:200]})
            save_state(project_dir, cfg, tasks, pool)

            if verdict in ("pass", "skipped"):
                break

        last_exit_code = exit_code

        # [I] Impact
        tasks, pool = load_state(project_dir, cfg)
        task = task_by_id(tasks, current_task_id)
        if task is not None:
            post = capture_post_snapshot(project_dir, task)
            pre_snap = task.get("impact", {}).get("pre", pre)
            compute_impact(project_dir, task, pre_snap, post)

        # [K] artifact
        artifact_path = write_task_artifact(
            project_dir, cfg, task, agent_name, role, exit_code, prompt_file, summary_note
        )
        if task is not None:
            append_artifact(task, artifact_path)

        # Verdict branching
        if verdict == "fail":
            if task is not None:
                mark_unverified(task, "harness_fail_exceeded")
                record_task_lesson(project_dir, task, "unverified")
            finish_task(tasks, current_task_id, role, "unverified",
                result={"exit_code": exit_code, "artifact": str(artifact_path), "finished_by": agent_name,
                        "error": f"verification failed: {verify_details[:200]}"})
        elif role.endswith("-coder") or role == "coder":
            finish_task(tasks, current_task_id, role, None,
                result={"exit_code": exit_code, "artifact": str(artifact_path), "finished_by": agent_name,
                        "error": None if exit_code == 0 else f"worker exited with code {exit_code}"})
            save_state(project_dir, cfg, tasks, pool)
            task = task_by_id(tasks, current_task_id)
            if task is not None and (enforce_review or task.get("policy", {}).get("enforce_review")):
                enter_review_gate(project_dir, cfg, tasks, task)
            elif task is not None and exit_code == 0:
                enqueue_followup_tasks(project_dir, cfg, tasks, task)
        elif role == "reviewer":
            v, reasons = parse_reviewer_verdict(artifact_path)
            finish_task(tasks, current_task_id, role, "reviewed",
                result={"exit_code": exit_code, "artifact": str(artifact_path), "finished_by": agent_name,
                        "verdict": v, "error": None})
            save_state(project_dir, cfg, tasks, pool)
            tasks, pool = load_state(project_dir, cfg)
            task = task_by_id(tasks, current_task_id)
            if task is not None:
                apply_review_verdict(project_dir, cfg, tasks, task, v, reasons)
        else:
            finish_task(tasks, current_task_id, role, None,
                result={"exit_code": exit_code, "artifact": str(artifact_path), "finished_by": agent_name,
                        "error": None if exit_code == 0 else f"worker exited with code {exit_code}"})
            if exit_code == 0:
                task = task_by_id(tasks, current_task_id)
                if task is not None:
                    enqueue_followup_tasks(project_dir, cfg, tasks, task)

        if task is not None:
            mape_k_record(task, "knowledge", {"artifact": str(artifact_path)})
        save_state(project_dir, cfg, tasks, pool)
        tasks, pool = load_state(project_dir, cfg)

        if not loop_enabled:
            break

        # --- mark idle in pool so watcher tracks correctly, then loop ---
        tasks, pool = load_state(project_dir, cfg)
        for agent in pool["agents"]:
            if agent["name"] == agent_name:
                agent["status"] = "idle"
                agent["task_id"] = None
                agent["idle_since"] = now_iso()
        save_state(project_dir, cfg, tasks, pool)

        task_id = None  # claim next task on next iteration

    # --- exit: remove from pool ---
    tasks, pool = load_state(project_dir, cfg)
    remove_agent(pool, agent_name)
    save_state(project_dir, cfg, tasks, pool)
    return last_exit_code


def cmd_help() -> None:
    print(
        "\n".join([
            "teamstart — tmux multi-agent runtime",
            "",
            "Usage:",
            "  teamstart [project-dir]      Start (첫 실행 시 자동으로 마법사 실행)",
            "  teamstart wizard             설정 마법사 수동 실행",
            "  teamstart update             최신 변경사항 pull 및 런타임 갱신",
            "  teamstart update --sync-config   위에 더해 .ai-config.yaml 누락 역할/섹션 동기화",
            "  teamstart update --install-hook  세션 종료 시 자동 커밋 훅 설치",
            "  teamstart update --remove-hook   자동 커밋 훅 제거",
            "  teamstart doctor             환경 및 프로젝트 설정 점검",
            "  teamstart help               도움말 표시",
            "",
            "Standalone commands:",
            "  teamupdate                   Same as teamstart update",
            "  teaminit [project-dir]       Initialize project scaffolding only",
            "  teamclean [project-dir]      Stop session and remove runtime state",
            "",
            "Runtime commands (via runtime.py):",
            "  init        Initialize project scaffolding without starting tmux",
            "  clean       Stop tmux session and remove runtime state",
            "  enqueue     Push a task into the queue",
            "  workflow    Enqueue a full pipeline workflow",
            "    --name standard   Codex 미사용 표준 워크플로우 (13단계)",
            "    --name codex      Codex 사용 워크플로우 (12단계)",
            "  status      Print queue and agent status",
            "  spawn       Manually spawn a worker pane",
            "  kill        Kill a named worker pane",
            "  lesson      Record a lesson learned",
            "  lessons     List recorded lessons",
            "",
            "Environment variables:",
            "  TMUX_RUNTIME_HOME     Override shared runtime location (default: ~/.tmux-runtime)",
            "  TMUX_BIN              Use a custom tmux binary (default: tmux)",
            "  AI_WATCH_INTERVAL     Watcher polling interval in seconds (default: 5)",
            "  AI_IDLE_TTL_SECONDS   Seconds before idle worker pane is closed (default: 120)",
            "  AI_AGENT_LOOP              Agent task continuation loop, true/false (default: true)",
            "  AI_AGENT_IDLE_CHECKS       Max idle polls before agent exits (default: 6)",
            "  AI_AGENT_IDLE_POLL         Seconds between idle polls (default: 5)",
            "  AI_HARNESS_MAX_ATTEMPTS    Max harness verify retries per task (default: 3)",
            "  AI_REVIEW_MAX_REJECTIONS   Max adversarial review rejections before blocked (default: 3)",
            "",
            "Docs: https://github.com/picory/tmux-team-agent",
        ])
    )


def _extract_agent_block(template_lines: list[str], role_name: str) -> str | None:
    """Return the YAML block for role_name from template lines, or None if not found."""
    in_agents = False
    in_block = False
    block_lines: list[str] = []

    for line in template_lines:
        stripped = line.strip()
        if not in_agents:
            if stripped == "agents:":
                in_agents = True
            continue
        # leaving agents section: non-indented, non-empty, non-comment real key
        if line and not line[0].isspace() and stripped and not stripped.startswith("#"):
            break
        if stripped == f"- name: {role_name}":
            in_block = True
            block_lines = [line]
        elif in_block:
            if stripped.startswith("- name:"):
                break  # next agent block started
            block_lines.append(line)

    while block_lines and not block_lines[-1].strip():
        block_lines.pop()
    return "\n".join(block_lines) if block_lines else None


def sync_config(project_dir: Path) -> list[str]:
    """Backup .ai-config.yaml then add missing agents/sections from the template.

    Never removes or modifies existing entries — additive only.
    Returns list of human-readable change descriptions.
    """
    config_path = project_dir / ".ai-config.yaml"
    template_path = template_root() / ".ai-config.yaml"
    if not config_path.exists() or not template_path.exists():
        return []

    existing_cfg = parse_ai_config(config_path)
    existing_roles = {a["name"] for a in existing_cfg.agents}

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as fh:
        fh.write(read_text(template_path).replace("__PROJECT_NAME__", existing_cfg.project))
        tmp_path = Path(fh.name)
    template_cfg = parse_ai_config(tmp_path)
    os.unlink(tmp_path)

    missing_agents = [a for a in template_cfg.agents if a["name"] not in existing_roles]
    existing_text = read_text(config_path)
    has_limits = "limits:" in existing_text or "# limits:" in existing_text

    if not missing_agents and has_limits:
        return []

    # --- backup ---
    date_str = datetime.now().strftime("%Y%m%d")
    backup_path = config_path.with_name(f".ai-config.yaml.{date_str}.bak")
    shutil.copy2(str(config_path), str(backup_path))

    template_lines = read_text(template_path).splitlines()
    existing_lines = existing_text.splitlines()
    changes: list[str] = []

    # --- insert missing agent blocks before paths:/limits: section ---
    if missing_agents:
        insert_idx = len(existing_lines)
        for i, line in enumerate(existing_lines):
            s = line.strip()
            if line and not line[0].isspace() and s and not s.startswith("#") and ":" in s:
                key = s.split(":")[0].strip()
                if key in ("paths", "limits"):
                    insert_idx = i
                    break

        new_block_lines: list[str] = []
        added_names: list[str] = []
        for agent in missing_agents:
            block = _extract_agent_block(template_lines, agent["name"])
            if block:
                new_block_lines.append("")
                new_block_lines.extend(block.splitlines())
                added_names.append(agent["name"])

        if new_block_lines:
            # ensure blank line before the section that follows
            existing_lines = (
                existing_lines[:insert_idx]
                + new_block_lines
                + [""]
                + existing_lines[insert_idx:]
            )
            changes.append(f"roles added: {', '.join(added_names)}")

    # --- append limits section comment if missing ---
    full_text = "\n".join(existing_lines)
    if not has_limits and "limits:" not in full_text and "# limits:" not in full_text:
        existing_lines += [
            "",
            "# limits:",
            "#   min_free_memory_mb: 2048   # hold off new agent spawns when free RAM drops below this",
        ]
        changes.append("section added: limits (commented out)")

    write_text(config_path, "\n".join(existing_lines) + "\n")
    changes.append(f"backup: {backup_path.name}")
    return changes


def cmd_update(
    project_dir: Path,
    sync_config_flag: bool = False,
    install_hook_flag: bool = False,
    remove_hook_flag: bool = False,
) -> int:
    """Pull latest changes from the repo and re-run setup."""
    # Hook-only operations don't need git pull
    if install_hook_flag and not remove_hook_flag:
        ok = install_commit_hook(project_dir)
        print("commit-session hook installed." if ok else "commit-session hook already installed.")
        return 0

    if remove_hook_flag:
        ok = remove_commit_hook(project_dir)
        print("commit-session hook removed." if ok else "commit-session hook was not installed.")
        return 0

    # runtime.py is symlinked: resolve() gives <repo>/runtime/lib/runtime.py
    resolved = Path(__file__).resolve()
    repo_root = resolved.parents[2]

    if not (repo_root / ".git").exists():
        print(f"error: could not locate git repo from {resolved}")
        print("       Is the runtime installed via the git clone? (not a plain copy)")
        return 1

    print(f"repo: {repo_root}")

    print("\n-- git pull --")
    result = run(["git", "-C", str(repo_root), "pull"], check=False)
    if result.returncode != 0:
        print("warning: git pull failed — continuing with current version")

    print("\n-- setup --")
    setup(repo_root, project_dir)

    if sync_config_flag:
        print("\n-- config sync --")
        sync_changes = sync_config(project_dir)
        if sync_changes:
            for change in sync_changes:
                print(f"  {change}")
        else:
            print("  config up to date")

    print("\n-- skills --")
    updated = reinstall_skills()
    if updated:
        print(f"skills updated: {', '.join(updated)}")

    print("\nruntime updated.")
    return 0


def cmd_doctor(project_dir: Path | None) -> int:
    ok = True

    def check(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        status = "ok  " if passed else "FAIL"
        if not passed:
            ok = False
        suffix = f"  ({detail})" if detail else ""
        print(f"  [{status}] {label}{suffix}")

    print("tmux-team-agent doctor\n")

    # --- binaries ---
    print("Binaries:")
    check("tmux", command_exists("tmux"), shutil.which("tmux") or "not found")
    check("python3", command_exists("python3"), shutil.which("python3") or "not found")
    claude_bin = shutil.which("claude")
    check("claude", claude_bin is not None, claude_bin or "not found")
    codex_bin = shutil.which("codex")
    codex_label = codex_bin if codex_bin else "not found (optional — enables codex workflow)"
    print(f"  [{'ok  ' if codex_bin else 'skip'}] codex  ({codex_label})")

    # --- runtime install ---
    print("\nRuntime:")
    rt_home = runtime_home()
    check("TMUX_RUNTIME_HOME exists", rt_home.is_dir(), str(rt_home))
    for sub_name in ["bin", "scripts", "lib"]:
        check(f"  {sub_name}/", (rt_home / sub_name).is_dir())
    check("  lib/runtime.py", (rt_home / "lib" / "runtime.py").exists())

    # --- PATH / symlinks ---
    print("\nPATH:")
    local_bin = Path.home() / ".local" / "bin"
    path_dirs = os.environ.get("PATH", "").split(":")
    check("~/.local/bin in PATH", str(local_bin) in path_dirs, str(local_bin))
    for cmd_name in ["teamstart", "teaminit", "teamclean", "teamupdate"]:
        link = local_bin / cmd_name
        check(f"  {cmd_name}", link.exists() or link.is_symlink())

    # --- environment variables ---
    print("\nEnvironment:")
    watch_interval = os.environ.get("AI_WATCH_INTERVAL", "5 (default)")
    idle_ttl = os.environ.get("AI_IDLE_TTL_SECONDS", "120 (default)")
    tmux_bin_env = os.environ.get("TMUX_BIN", "tmux (default)")
    print(f"  AI_WATCH_INTERVAL     = {watch_interval}")
    print(f"  AI_IDLE_TTL_SECONDS   = {idle_ttl}")
    print(f"  AI_AGENT_LOOP         = {os.environ.get('AI_AGENT_LOOP', 'true (default)')}")
    print(f"  AI_AGENT_IDLE_CHECKS  = {os.environ.get('AI_AGENT_IDLE_CHECKS', '6 (default)')}")
    print(f"  AI_AGENT_IDLE_POLL    = {os.environ.get('AI_AGENT_IDLE_POLL', '5 (default)')}")
    print(f"  TMUX_BIN              = {tmux_bin_env}")
    print(f"  TMUX_RUNTIME_HOME     = {os.environ.get('TMUX_RUNTIME_HOME', f'{rt_home} (default)')}")

    # --- memory + spawn cap ---
    print("\nMemory & Spawn Cap:")
    free_mb = get_free_memory_mb()
    if free_mb is not None:
        print(f"  free (approx): {free_mb} MB")
    else:
        print("  free: unavailable")
    if project_dir is not None and (project_dir / ".ai-config.yaml").exists():
        cfg_tmp = parse_ai_config(project_dir / ".ai-config.yaml")
        threshold = int(cfg_tmp.limits.get("min_free_memory_mb", 0))
        if threshold > 0:
            status = "ok  " if (free_mb or 0) >= threshold else "FAIL"
            print(f"  [{status}] min_free_memory_mb = {threshold} MB")
        tasks_tmp = load_json((project_dir / cfg_tmp.task_dir).resolve() / "tasks.json", {"tasks": []})
        base_cap, effective_cap, burst_mode = compute_spawn_cap(cfg_tmp, tasks_tmp)
        auto_n = len([a for a in cfg_tmp.agents if a.get("name") != "leader" and a.get("scale") == "auto"])
        print(f"  auto-scale roles : {auto_n}")
        print(f"  base cap         : {base_cap}  (floor({auto_n} × 0.5), clamped [1,8])")
        print(f"  burst cap        : {max(1, min(8, int(auto_n * 0.75)))}  (floor({auto_n} × 0.75), clamped [1,8])")
        print(f"  effective cap    : {effective_cap}{' [BURST]' if burst_mode else ''}")
        print(f"  absolute hard limit: 8")

    # --- project ---
    if project_dir is not None and project_dir.is_dir():
        print(f"\nProject: {project_dir}")
        config_file = project_dir / ".ai-config.yaml"
        check(".ai-config.yaml", config_file.exists())
        agents_dir = project_dir / ".ai-agents"
        check(".ai-agents/", agents_dir.is_dir())
        if agents_dir.is_dir():
            expected_roles = ["leader", "backend-coder", "frontend-coder", "reviewer", "qa", "docs-writer"]
            for role in expected_roles:
                check(f"  .ai-agents/{role}.md", (agents_dir / f"{role}.md").exists())
        check("tasks/", (project_dir / "tasks").is_dir())
        check("outputs/", (project_dir / "outputs").is_dir())
        check(".ai-state/", (project_dir / ".ai-state").is_dir())
    else:
        print("\nProject: (pass a project-dir to check project config)")

    print()
    if ok:
        print("All checks passed.")
        return 0
    else:
        print("Some checks failed. Run './setup.sh' to repair the runtime install.")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    setup_parser = sub.add_parser("setup")
    setup_parser.add_argument("--repo-root", required=True)
    setup_parser.add_argument("--project-dir", required=True)

    init_parser = sub.add_parser("init")
    init_parser.add_argument("--project-dir", required=True)

    clean_parser = sub.add_parser("clean")
    clean_parser.add_argument("--project-dir", required=True)

    start_parser = sub.add_parser("start")
    start_parser.add_argument("--project-dir", required=True)

    leader_parser = sub.add_parser("leader-loop")
    leader_parser.add_argument("--project-dir", required=True)

    leader_session_parser = sub.add_parser("leader-session")
    leader_session_parser.add_argument("--project-dir", required=True)

    watch_parser = sub.add_parser("watch")
    watch_parser.add_argument("--project-dir", required=True)

    enqueue_parser = sub.add_parser("enqueue")
    enqueue_parser.add_argument("--project-dir", required=True)
    enqueue_parser.add_argument("--role", required=True)
    enqueue_parser.add_argument("--text", required=True)
    enqueue_parser.add_argument("--created-by", default="leader")
    enqueue_parser.add_argument("--priority", default="normal")
    enqueue_parser.add_argument("--scope", default="task")

    workflow_parser = sub.add_parser("workflow")
    workflow_parser.add_argument("--project-dir", required=True)
    workflow_parser.add_argument("--name", required=True, help="workflow name: standard | codex")
    workflow_parser.add_argument("--task", required=True, help="task description for all stage titles")

    status_parser = sub.add_parser("status")
    status_parser.add_argument("--project-dir", required=True)

    spawn_parser = sub.add_parser("spawn")
    spawn_parser.add_argument("--project-dir", required=True)
    spawn_parser.add_argument("--role", required=True)
    spawn_parser.add_argument("--agent-name")
    spawn_parser.add_argument("--task-id")

    kill_parser = sub.add_parser("kill")
    kill_parser.add_argument("--project-dir", required=True)
    kill_parser.add_argument("--agent-name", required=True)

    agent_parser = sub.add_parser("run-agent")
    agent_parser.add_argument("--project-dir", required=True)
    agent_parser.add_argument("--role", required=True)
    agent_parser.add_argument("--agent-name", required=True)
    agent_parser.add_argument("--task-id")

    doctor_parser = sub.add_parser("doctor")
    doctor_parser.add_argument("--project-dir")

    update_parser = sub.add_parser("update")
    update_parser.add_argument("--project-dir", default=None)
    update_parser.add_argument("--sync-config", action="store_true",
                               help="merge template config into existing .ai-config.yaml")
    update_parser.add_argument("--install-hook", action="store_true",
                               help="install commit-session.sh Stop hook into this project")
    update_parser.add_argument("--remove-hook", action="store_true",
                               help="remove commit-session.sh Stop hook from this project")

    wizard_parser = sub.add_parser("wizard")
    wizard_parser.add_argument("--project-dir", default=None)

    sub.add_parser("help")

    lesson_parser = sub.add_parser("lesson")
    lesson_parser.add_argument("--project-dir", required=True)
    lesson_parser.add_argument("--role", default=None, help="target role (omit for all roles)")
    lesson_parser.add_argument("--title", required=True)
    lesson_parser.add_argument("--detail", required=True)
    lesson_parser.add_argument("--task-id", default=None)

    lessons_parser = sub.add_parser("lessons")
    lessons_parser.add_argument("--project-dir", required=True)
    lessons_parser.add_argument("--role", default=None)

    args = parser.parse_args()

    if args.command == "setup":
        setup(Path(args.repo_root).resolve(), Path(args.project_dir).resolve())
        return 0
    if args.command == "init":
        ensure_project(Path(args.project_dir).resolve())
        print(f"initialized {args.project_dir}")
        return 0
    if args.command == "clean":
        clean(Path(args.project_dir).resolve())
        return 0
    if args.command == "start":
        start(Path(args.project_dir).resolve())
        return 0
    if args.command == "leader-loop":
        leader_loop(Path(args.project_dir).resolve())
        return 0
    if args.command == "leader-session":
        return leader_session(Path(args.project_dir).resolve())
    if args.command == "watch":
        watch(Path(args.project_dir).resolve())
        return 0
    if args.command == "enqueue":
        task_id = enqueue_task_cli(
            Path(args.project_dir).resolve(),
            args.role,
            args.text,
            created_by=args.created_by,
            priority=args.priority,
            scope=args.scope,
        )
        print(task_id)
        return 0
    if args.command == "workflow":
        wf_ids = enqueue_workflow(Path(args.project_dir).resolve(), args.name, args.task)
        print(f"workflow '{args.name}' enqueued: {len(wf_ids)} stages")
        for wf_id in wf_ids:
            print(f"  {wf_id}")
        return 0
    if args.command == "status":
        print(summarize_status(Path(args.project_dir).resolve()))
        return 0
    if args.command == "spawn":
        name = spawn_agent(Path(args.project_dir).resolve(), args.role, args.agent_name, args.task_id)
        print(name)
        return 0
    if args.command == "kill":
        kill_agent(Path(args.project_dir).resolve(), args.agent_name)
        return 0
    if args.command == "run-agent":
        return run_agent(Path(args.project_dir).resolve(), args.role, args.agent_name, args.task_id)
    if args.command == "doctor":
        project_dir = Path(args.project_dir).resolve() if args.project_dir else None
        return cmd_doctor(project_dir)
    if args.command == "help":
        cmd_help()
        return 0
    if args.command == "update":
        project_dir = Path(args.project_dir).resolve() if args.project_dir else Path.cwd()
        return cmd_update(
            project_dir,
            sync_config_flag=args.sync_config,
            install_hook_flag=args.install_hook,
            remove_hook_flag=args.remove_hook,
        )
    if args.command == "wizard":
        project_dir = Path(args.project_dir).resolve() if args.project_dir else Path.cwd()
        cmd_wizard(project_dir)
        return 0
    if args.command == "lesson":
        lesson_id = record_lesson(
            Path(args.project_dir).resolve(),
            args.role,
            args.title,
            args.detail,
            source_task_id=args.task_id,
        )
        print(f"lesson recorded: {lesson_id}")
        return 0
    if args.command == "lessons":
        print(list_lessons_text(Path(args.project_dir).resolve(), args.role))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
