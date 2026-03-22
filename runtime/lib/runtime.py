#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
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
    value = os.environ.get("CMUX_RUNTIME_HOME") or str(Path.home() / ".cmux-runtime")
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


def run(cmd: list[str], capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        capture_output=capture,
    )


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def mux_supports_tmux_cli(name: str) -> bool:
    probe_session = "__ai_mux_probe__"
    try:
        result = subprocess.run(
            [name, "new-session", "-d", "-s", probe_session, "true"],
            text=True,
            capture_output=True,
        )
    except FileNotFoundError:
        return False

    if result.returncode != 0:
        output = f"{result.stdout}\n{result.stderr}".lower()
        if "unknown command" in output or "not found" in output:
            return False
        return False

    subprocess.run([name, "kill-session", "-t", probe_session], text=True, capture_output=True)
    return True


def detect_mux() -> str:
    preferred = os.environ.get("AI_MUX_BIN")
    if preferred:
        if mux_supports_tmux_cli(preferred):
            return preferred
        if preferred != "tmux" and command_exists("tmux"):
            return "tmux"
        raise SystemExit(f"{preferred} is configured but does not support tmux-compatible session commands.")
    if command_exists("cmux") and mux_supports_tmux_cli("cmux"):
        return "cmux"
    if command_exists("tmux"):
        return "tmux"
    if command_exists("cmux"):
        raise SystemExit("cmux is installed, but this runtime currently requires tmux-compatible session commands. Install tmux or force AI_MUX_BIN=tmux.")
    raise SystemExit("Neither cmux nor tmux is installed.")


def session_name(project_dir: Path) -> str:
    return f"ai-{safe_name(project_dir.name)}"


@dataclass
class Config:
    project: str
    agents: list[dict[str, Any]]
    paths: dict[str, str]

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

        if current_section == "paths" and ":" in stripped:
            key, value = stripped.split(":", 1)
            root["paths"][key.strip()] = parse_scalar(value.strip())
            continue

    return Config(
        project=str(root.get("project", path.parent.name)),
        agents=list(root.get("agents", [])),
        paths=dict(root.get("paths", {})),
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
        ".ai-agents/backend-coder.md",
        ".ai-agents/frontend-coder.md",
        ".ai-agents/desktop-coder.md",
        ".ai-agents/crawler-coder.md",
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


def merge_prompt(project_dir: Path, role: str) -> str:
    base_path = prompt_root() / f"{role}.base.md"
    project_path = project_dir / ".ai-agents" / f"{role}.md"
    chunks: list[str] = []
    if base_path.exists():
        chunks.append(read_text(base_path).strip())
    if project_path.exists():
        chunks.append(read_text(project_path).strip())
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
        if role not in {"leader", "reviewer", "qa", "docs-writer"}:
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
            "cmux",
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
    target = f"{session}:{window_name}"
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
    return f"tasks: {task_summary}\nagents: {active_agents}"


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
            "- Prefer backend-coder, frontend-coder, desktop-coder, crawler-coder, reviewer, qa, and docs-writer over generic work.",
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
    for task in tasks["tasks"]:
        if task["role"] == role and task["status"] == "pending":
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


def clean_missing_windows(project_dir: Path, cfg: Config, pool: dict[str, Any]) -> None:
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
    write_text(artifact_path, "\n".join(lines))
    return artifact_path


def enqueue_followup_tasks(project_dir: Path, cfg: Config, tasks: dict[str, Any], pool: dict[str, Any], task: dict[str, Any]) -> None:
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
                create_task(
                    project_dir,
                    "docs-writer",
                    f"Update docs for completed implementation: {title}",
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


def spawn_agent(project_dir: Path, role: str, agent_name: str | None, task_id: str | None) -> str:
    cfg = ensure_project(project_dir)
    tasks, pool = load_state(project_dir, cfg)
    clean_missing_windows(project_dir, cfg, pool)

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


def setup(repo_root: Path, project_dir: Path) -> None:
    rt_home = runtime_home()
    ensure_dir(rt_home)
    for name in ["bin", "scripts", "prompts", "templates", "lib"]:
        ensure_dir(rt_home / name)

    mapping = {
        repo_root / "runtime" / "bin" / "teamstart": rt_home / "bin" / "teamstart",
        repo_root / "runtime" / "bin" / "teaminit": rt_home / "bin" / "teaminit",
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

    for src_dir_name in ["prompts", "templates"]:
        src_dir = repo_root / "runtime" / src_dir_name if src_dir_name == "prompts" else repo_root / "templates"
        dest_dir = rt_home / src_dir_name
        if dest_dir.exists() or dest_dir.is_symlink():
            shutil.rmtree(dest_dir, ignore_errors=True)
        shutil.copytree(src_dir, dest_dir)

    local_bin = Path.home() / ".local" / "bin"
    ensure_dir(local_bin)
    for name in ["teamstart", "teaminit"]:
        link = local_bin / name
        target = rt_home / "bin" / name
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(target)

    ensure_project(project_dir)

    path_hint = str(local_bin)
    print(f"runtime installed at {rt_home}")
    print(f"project initialized at {project_dir}")
    print(f"ensure {path_hint} is on PATH")


def start(project_dir: Path) -> None:
    cfg = ensure_project(project_dir)
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
    intake_role = default_intake_role(cfg)
    print("leader ready")
    print("plain text => auto-routed specialist task")
    print("/review <text> => reviewer task")
    print("/qa <text> => qa task")
    print("/docs <text> => docs-writer task")
    print("/spawn <role> [text] => enqueue a task for a specific role")
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
        role = infer_role_from_text(cfg, line)
        task_id = create_task(project_dir, role, line)
        print(f"queued {role} task {task_id}")


def watch(project_dir: Path) -> None:
    cfg = ensure_project(project_dir)
    poll_seconds = int(os.environ.get("AI_WATCH_INTERVAL", "5"))
    idle_ttl_seconds = int(os.environ.get("AI_IDLE_TTL_SECONDS", "120"))
    print(f"watcher ready for {project_dir}")
    print(f"claude available: {'yes' if claude_available(project_dir) else 'no'}")

    while True:
        tasks, pool = load_state(project_dir, cfg)
        clean_missing_windows(project_dir, cfg, pool)
        refresh_agent_states(tasks, pool)

        pending_by_role: dict[str, int] = {}
        running_by_role: dict[str, int] = {}
        for task in tasks["tasks"]:
            if task["status"] == "pending":
                pending_by_role[task["role"]] = pending_by_role.get(task["role"], 0) + 1
        for agent in pool["agents"]:
            running_by_role[agent["role"]] = running_by_role.get(agent["role"], 0) + 1

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
                name = spawn_agent(project_dir, role, None, None)
                print(f"spawned {name}")
                running += 1
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


def run_agent(project_dir: Path, role: str, agent_name: str, task_id: str | None) -> int:
    cfg = ensure_project(project_dir)
    tasks, pool = load_state(project_dir, cfg)
    prompt = merge_prompt(project_dir, role)
    task: dict[str, Any] | None = None

    if task_id:
        for item in tasks["tasks"]:
            if item["id"] == task_id:
                task = item
                break
        if task is None:
            raise SystemExit(f"Task not found: {task_id}")
        if task.get("status") == "pending":
            task["status"] = "running"
            task["agent"] = agent_name
            task["started_at"] = now_iso()
            task["updated_at"] = now_iso()
            task["attempts"] = int(task.get("attempts", 0)) + 1
            save_state(project_dir, cfg, tasks, pool)

    payload_lines = [
        f"Role: {role}",
        f"Agent: {agent_name}",
        f"Project: {cfg.project}",
    ]
    if task:
        payload_lines.append(f"Task ID: {task['id']}")
        payload_lines.append(f"Task: {task['title']}")

    prompt_file = project_dir / ".ai-state" / f"{agent_name}.prompt.txt"
    write_text(prompt_file, prompt + "\n\n" + "\n".join(payload_lines) + "\n")

    print(f"[{agent_name}] starting role={role}")
    if task:
        print(f"[{agent_name}] task={task['title']}")
    print(f"[{agent_name}] prompt file={prompt_file}")

    exit_code = 0
    summary_note = "Prompt prepared but no worker session was launched."
    if claude_available(project_dir):
        initial_prompt = "\n".join(payload_lines)
        cmd = [
            "claude",
            "--dangerously-skip-permissions",
            "--append-system-prompt",
            prompt,
            "-n",
            agent_name,
            initial_prompt,
        ]
        exit_code = subprocess.run(cmd, cwd=project_dir).returncode
        summary_note = "Worker session finished. Review the terminal transcript for the full interaction."
    else:
        print("Claude CLI or .claude config not available. Prompt prepared but no agent was launched.")

    tasks, pool = load_state(project_dir, cfg)
    if task_id:
        task = task_by_id(tasks, task_id)
        artifact_path = write_task_artifact(project_dir, cfg, task, agent_name, role, exit_code, prompt_file, summary_note)
        if task is not None:
            append_artifact(task, artifact_path)
        finish_task(
            tasks,
            task_id,
            role,
            "failed" if exit_code else None,
            result={
                "exit_code": exit_code,
                "artifact": str(artifact_path),
                "finished_by": agent_name,
                "error": None if exit_code == 0 else f"worker exited with code {exit_code}",
            },
        )
        save_state(project_dir, cfg, tasks, pool)
        task = task_by_id(tasks, task_id)
        if task is not None and exit_code == 0:
            enqueue_followup_tasks(project_dir, cfg, tasks, pool, task)
            tasks, pool = load_state(project_dir, cfg)
    remove_agent(pool, agent_name)
    save_state(project_dir, cfg, tasks, pool)
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    setup_parser = sub.add_parser("setup")
    setup_parser.add_argument("--repo-root", required=True)
    setup_parser.add_argument("--project-dir", required=True)

    init_parser = sub.add_parser("init")
    init_parser.add_argument("--project-dir", required=True)

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

    args = parser.parse_args()

    if args.command == "setup":
        setup(Path(args.repo_root).resolve(), Path(args.project_dir).resolve())
        return 0
    if args.command == "init":
        ensure_project(Path(args.project_dir).resolve())
        print(f"initialized {args.project_dir}")
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
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
