---
name: blueprint
description: |
  자동화/에이전트 시스템 설계서 생성. 인터뷰로 요구사항을 정리하고
  tmux-team-agent 기준의 통합 설계 문서를 작성한다.
  "blueprint", "설계서", "에이전트 설계", "자동화 설계", "workflow design" 요청 시 사용.
allowed-tools:
  - Bash
  - Read
  - Write
  - Glob
  - Grep
---

# Blueprint — 에이전트 시스템 설계서 생성

## 개요

사용자와 짧은 인터뷰를 진행하고 `blueprint-<task>.md` 설계서를 작성한다.
기본 가정: tmux-team-agent 런타임 + Claude Code 에이전트.

---

## Step 1: 기존 문서 스캔

```bash
ls *.md 2>/dev/null
ls blueprint-*.md spec-*.md *-spec.md *PRD*.md *기획*.md *설계*.md 2>/dev/null || true
cat CLAUDE.md 2>/dev/null | head -30 || true
```

관련 문서가 있으면 내용을 읽고 인터뷰 전에 요약한다.

---

## Step 2: 인터뷰 (최대 3라운드)

아래 4개 영역에서 **모르는 것만** 질문한다. 한 번에 최대 3개 질문.
모르는 항목은 합리적 기본값을 적용하고 문서에 가정으로 명시한다.

| 영역 | 확인할 최소 항목 |
|---|---|
| 목표 및 성공 기준 | 완료 조건, 실패 조건 |
| 작업 절차 | 입력, 출력, 분기 조건, 사람 개입 포인트 |
| 실행 환경 | 파일 형식, API, 외부 도구, 저장 위치 |
| 제약 | 정확도, 비용, 속도, 보안, 권한 범위 |

3라운드 후에는 미확인 항목을 가정으로 처리하고 문서 작성으로 넘어간다.

---

## Step 3: 설계서 작성

출력 파일: `./blueprint-<task-name>.md`

설계서 구조:

```
# Blueprint: <제목>

## 0. 목표 및 배경
### 배경
### 목표
### 성공 기준
### 범위 (In / Out of Scope)

## 1. 에이전트 구성
### 투입 역할
- leader: ...
- <role>: ...
### .ai-config.yaml 권장 설정

## 2. 워크플로우
### 입력 / 출력
### 엔드투엔드 흐름
### 단계별 상세 (Step NN)
  - 목표
  - 입력/출력
  - 판단 영역 (LLM) vs 처리 영역 (코드/스크립트)
  - 성공 기준
  - 실패 처리

## 3. 제약 및 가정
## 4. 다음 액션
```

---

## Step 4: 완료 보고

```
설계서 작성 완료
  파일: ./blueprint-<task-name>.md
  투입 역할: <역할 목록>
  예상 태스크 수: <N>
  다음 단계: teamstart 후 leader에게 설계서 전달
```
