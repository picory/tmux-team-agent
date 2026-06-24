# Harness · Hermes · MAPE-K 통합 아키텍처

> teamstart 멀티에이전트 시스템의 제어 모델. 적대적 게이트(`.ai-agents/*.md`)가 실제로 무엇을
> 구현하는지를 자율컴퓨팅 표준(MAPE-K)으로 정식화한다.

## 1. 세 개념의 관계 (경쟁이 아니라 한 몸)

| 개념 | 정체 | 한 줄 |
|------|------|------|
| **MAPE-K** | 제어 루프의 *모양* | Monitor → Analyze → Plan → Execute, 공유 Knowledge 위에서 |
| **Harness(하네스)** | 루프를 돌리는 *컨트롤러* | 최종 verdict 소유·반려 라우팅·에스컬레이션·규칙 주입 |
| **Hermes(헤르메스)** | 메시지 *버스* | 에이전트↔하네스 간 task·claim·evidence·verdict를 나르는 전송/계약 |

요약: **MAPE-K는 무엇이 도는가, 하네스는 누가 판정하는가, 헤르메스는 어떻게 전달되는가.**

## 2. MAPE-K 매핑 (지금 있는 것 → 단계)

| 단계 | teamstart 구성요소 | 입력/산출 |
|------|-------------------|-----------|
| **Monitor** | watcher(큐·팬 상태), qa 결과, 증거 수집(스크린샷·빌드 로그·테스트 리포트) | 센서 → 원시 신호 |
| **Analyze** | **하네스** verifier 판정, error_type 분류(Syntax/Logic/Dependency/Infra/Hallucination), reviewer/ux-designer 반려 | verdict·반려·에스컬레이션 결정 |
| **Plan** | leader/product-manager 태스크 분할·라우팅·재할당 | tasks.json 갱신 |
| **Execute** | coder(구현)·fix·deploy (이펙터: Edit/Write/build/commit) | 코드 변경·아티팩트 |
| **Knowledge** | tasks.json + claim-ledger + failure-patterns + lessons + 규칙/프롬프트 + 증거 | 모든 단계가 읽고 쓰는 단일 상태 |

## 3. Harness — 컨트롤러 (autonomic manager)

**책임**
- **최종 판정권 단독 보유.** coder/qa는 "완료"를 선언하지 못한다. 하네스가 claim별 verifier를 돌려 `pass|fail|unverified`를 기록한다.
- **반려 라우팅** (Analyze 정책):

| 반려 출처 | 조건 | 라우팅 |
|----------|------|--------|
| skeptic | 의존성/환각 | planner 재할당 |
| ux-designer | 레이아웃·가이드 이탈 | coder (불가피 시 leader 조정) |
| qa/test | Syntax/Logic | fix → 재검증 |
| qa/test | Dependency/Hallucination | skeptic → planner |
| qa/test | Infra | leader → 사용자 |
| reviewer | 요구 불일치/테스트 미흡/버그 | planner/test-harness/coder |
| 완료 게이트 | evidence 없음 | 원역할(unverified) |
| 공통 | loop_count > 5 | leader 에스컬레이션 → 사용자 |

- **preflight 규칙 주입**: failure-patterns를 읽어 "증거 없는 완료 금지" 등을 실행 전 주입.
- **불가침**: 검증 역할의 반려를 임의로 뒤집지 않는다(조정은 재검증으로 되돌리는 것).

## 4. Hermes — 메시지 버스 (계약)

에이전트·하네스 간 모든 통신은 아래 **메시지 카탈로그**로만 한다. 전송로는 inbox/`tasks.json`/이벤트.

**공통 봉투(envelope)**: `{ msg_id, type, from, to, task_id, ts }`

```
task      { task_id, title, acceptance_criteria[], dependencies[], design_guide?, target_files[] }
claim     { claim_id, claim_type, target, evidence_paths[], verifier, agent_summary }
evidence  { evidence_id, kind: screenshot|build_log|test_report|diff, path, meta }
verdict   { claim_id, verdict: pass|fail|unverified, verdict_reason, checked_by, checked_at }
reject    { from_role, target, reason, route_to, severity }
escalation{ task_id, reason: loop>5|infra|conflict, loop_count, to: leader|user }
approval  { gate: G1|G2, decision: approved|changes_requested, by: leader }
```

**계약 원칙**
- claim에 `evidence_paths`가 비면 하네스가 즉시 `unverified`.
- UI claim(`ui_fixed`·`layout_ok`)은 before/after 스크린샷·selector 증거 없으면 불인정.
- 자유 텍스트 성공 보고는 메시지 타입이 아니다 → 판정 근거로 인정 안 함.

## 5. Knowledge — 공유 지식베이스

| 구성 | 역할 | 쓰기 주체 |
|------|------|-----------|
| `tasks/tasks.json` | 태스크 큐(단일 진실원) | leader/Plan |
| **claim-ledger** | 주장·증거·판정 원장 | 하네스/Analyze |
| `failure-patterns` | 반복 허위/과장 보고 패턴 | 하네스(승격) |
| `lessons` | 런 종료 후 학습 | reflect |
| 규칙/`.ai-agents/*` | 정책(읽기 전용 K) | 사람/rules-engineer |
| 증거 아티팩트 | 스크린샷·로그·리포트 | Monitor/Execute |

**claim-ledger 스키마**
```
{ claim_id, claim_type, task_id, evidence_paths[], verifier,
  verdict: pass|fail|unverified, verdict_reason, checked_at, checked_by, loop_count }
```
즉 테스트 원장은 *범위 원장*일 뿐 아니라 **주장 검증 원장**이다.

## 6. 루프 (M→A→P→E over K, Hermes 위)

```
        ┌──────────────── Knowledge (tasks·claim-ledger·patterns·rules·evidence) ───────────────┐
        │                                                                                        │
   [Monitor]            [Analyze]               [Plan]                 [Execute]
   watcher/qa  ──evidence──▶ Harness ──verdict/reject──▶ leader/planner ──task──▶ coder/fix/deploy
        ▲                  (판정·라우팅·에스컬레이션)                                  │
        └───────────────────────── Hermes 메시지 버스 ─────────────────────────────────┘
```

## 7. 적대적 게이트와의 관계 (이미 도는 부분)

`.ai-agents/*.md`에 박힌 게이트가 MAPE-K의 **A(Analyze) 단계 구현체**다.
- ux-designer Design Review = UI의 Monitor+Analyze (가이드 대조 → 반려)
- qa 증거 기반 검증 = Analyze (verdict)
- test-harness-engineer 검증기 = Analyze의 verifier
- leader 완료 게이트·충돌 조정 = 하네스 정책

**대부분 암묵적으로 이미 돈다.** 이 문서의 목적은 그것을 *명시적 구조*로 끌어올리는 것.

## 8. 단계적 적용

- **지금**: 게이트 = 암묵 MAPE. 작동 중.
- **다음 1**: claim-ledger를 K로 명시(파일·스키마 확정).
- **다음 2**: Hermes 메시지 카탈로그를 런타임 계약으로 표준화(흩어진 JSON 통합).
- **다음 3**: runtime 루프에 M/A/P/E 라벨링(watcher=Monitor, 하네스=Analyze…).
