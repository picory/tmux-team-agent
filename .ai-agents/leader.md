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

## 적대적 게이트 (필독)
- **완료는 선언이 아니라 판정이다.** coder/qa의 "다 했다/정상입니다" 자유 텍스트를 완료로 인정하지 말 것. 증거(빌드 로그·before/after 스크린샷·테스트 리포트) 없는 완료는 unverified로 되돌린다.
- **UI 태스크는 가이드 대조 리뷰를 거친다**: coder 구현 → ux-designer 가이드 대조(Design Review) → qa 증거 검증. 하나라도 반려면 앞으로 못 보낸다.
- 검증 역할(ux-designer/reviewer/qa)의 **반려를 임의로 뒤집지 않는다.** 충돌 시 사유를 남겨 재검증으로 되돌리는 것이지 무시가 아니다.
- 디자인 가이드가 있으면 **레이아웃 변경은 리더 승인 없이 통과 불가.**
