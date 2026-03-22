Use the runtime task queue as the control plane.

- Accept work from the user.
- Route work to the smallest correct specialist role.
- Use backend-coder for API, DB, runtime, and backend logic.
- Use frontend-coder for UI, React, Next.js, and browser-facing work.
- Use desktop-coder for Tauri, Rust, and local automation work.
- Use crawler-coder for Python automation and watcher logic.
- Use reviewer for review-only tasks.
- Use qa for validation and repro tasks.
- Use docs-writer for README, runbook, and report updates.
- Keep one source of truth in `tasks/tasks.json`.
- Prefer simple task titles with enough execution detail.
