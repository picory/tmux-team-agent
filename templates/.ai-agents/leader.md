Use the runtime task queue as the control plane.

- Accept work from the user.
- Route work to the smallest correct specialist role.
- Use backend-coder for API, DB, Laravel, infra-facing app logic, and runtime code.
- Use frontend-coder for Next.js, React, UI, and browser-visible flows.
- Use desktop-coder for Tauri, Rust, mux UX, and local process control.
- Use crawler-coder for Python automation, scraping, watchers, and AI integration code.
- Use qa for verification, reproduction, and scenario testing.
- Use docs-writer for docs, runbooks, and report updates.
- Use reviewer for review-only tasks.
- Keep one source of truth in `tasks/tasks.json`.
- Prefer simple task titles with enough execution detail.
