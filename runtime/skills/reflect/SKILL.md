---
name: reflect
description: |
  tmux-team-agent 세션 마무리. 완료/실패한 태스크와 아웃풋을 분석해
  배운 점, 다음 액션, 문서 업데이트 포인트를 정리하고 lessons에 기록한다.
  "reflect", "세션 정리", "오늘 한 거 정리", "마무리", "wrap up" 요청 시 사용.
allowed-tools:
  - Bash
  - Read
  - Glob
  - Grep
  - Write
  - Edit
---

# Reflect — 세션 마무리 및 lessons 기록

## 개요

세션에서 실제로 변경된 내용을 기반으로 배운 점과 다음 액션을 추출한다.
추측하지 말고 파일과 태스크 기록에서 증거를 직접 읽어라.

---

## Step 1: 세션 상태 수집

```bash
# 프로젝트 루트 확인
pwd

# git 변경사항
git status --short
git diff --stat HEAD 2>/dev/null | tail -20

# 태스크 상태
cat tasks/tasks.json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
tasks = data.get('tasks', [])
for t in tasks:
    print(f\"[{t['status']:8}] ({t['role']}) {t['title']}\")
" 2>/dev/null || echo "tasks/tasks.json 없음"

# 아웃풋 목록
ls -lt outputs/ 2>/dev/null | head -10 || echo "outputs/ 없음"

# lessons 현황
python3 ~/.tmux-runtime/lib/runtime.py lessons --project-dir "$PWD" 2>/dev/null
```

---

## Step 2: 4가지 분석

아래 4가지를 실제 수행된 작업 기반으로 분석한다. 추측 항목은 제외한다.

1. **문서 업데이트 필요**: 구현 내용이 바뀌었는데 README/CLAUDE.md/설계서가 미반영된 것
2. **자동화 아이디어**: 반복 수동 작업 중 스킬/스크립트로 만들 수 있는 것
3. **배운 점 (lessons)**: 이번에 발견한 제약, 실수 패턴, 비직관적 동작
4. **다음 액션**: 당장 이어서 할 작업 1-3개 (구체적인 태스크 단위)

---

## Step 3: 요약 출력

아래 형식으로 출력한다:

```
=== Session Reflect ===

[문서 업데이트]
- ...

[자동화 아이디어]
- ...

[배운 점]
- ...

[다음 액션]
1. ...
2. ...
```

---

## Step 4: Lessons 기록 제안

배운 점 항목 중 **재발 방지가 필요한 것**을 사용자에게 보여주고 기록할지 확인한다.

기록할 경우:
```bash
python3 ~/.tmux-runtime/lib/runtime.py lesson \
  --project-dir "$PWD" \
  --role "<해당 역할 또는 생략>" \
  --title "<한 줄 요약>" \
  --detail "<재발 방지 방법>"
```

기록 후 확인:
```bash
python3 ~/.tmux-runtime/lib/runtime.py lessons --project-dir "$PWD"
```
