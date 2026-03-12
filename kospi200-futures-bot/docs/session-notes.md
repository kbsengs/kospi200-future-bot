# KOSPI200 선물 자동매매 봇 — 세션 노트

---

## 2026-03-12 세션 노트

### 전략 파라미터 현황

**1분봉 (config.yaml)**
- strategy: brando
- ema_length: 100
- mom_lookback: 5
- stop_atr_mult: 3.0
- bb_length: 20, bb_mult: 2.0
- kc_length: 20, kc_mult: 1.5
- timeframe: "1"

**5분봉 (config_5min.yaml)** — 이번 세션 신규 생성
- strategy: brando
- ema_length: 100
- mom_lookback: 10  (5분봉 스윕 최적값, 1분봉과 역전)
- stop_atr_mult: 3.0
- bb_length: 20, bb_mult: 2.0
- kc_length: 20, kc_mult: 1.5
- timeframe: "5"

### 백테스트 / 스윕 결과

**1분봉 브랜도 스윕 (48개 조합, 2025-09-10~12-19)**
- 저장: `docs/brando_sweep_results.md`
- 1위: EMA=200, look=3, stop=3.0 → 44,535,000원, PF=1.76, 승률=52.5%
- 현재 config(ema=100, look=5, stop=3.0): 13위 → 38,865,000원, PF=1.65
- 핵심 인사이트: mom_lookback=3이 최적 (현재 5 → 변경 시 약 560만원 차이)
- EMA 50/100/200 차이 미미 (~20만원)

**5분봉 브랜도 스윕 (48개 조합, 동일 기간)**
- 저장: `docs/brando_sweep_5min.md`
- 1위: EMA=100, look=10, stop=3.0 → 31,567,500원, PF=2.11, 승률=54.2%
- 5분봉 장점: PF 1.65→2.11, 승률 51%→55%, 거래횟수 871→186 (노이즈 감소)
- 5분봉 단점: 총손익 절대값 감소 (봉 수 적어 진입 기회 감소)
- 1분봉과 lookback 최적값 역전: 1분봉=3이 최적, 5분봉=10이 최적

### 오늘 거래 결과 요약
- 총 거래: 13건 (초기 사용자 보고는 7건)
- 수익: 0건 / 손실: 13건 / 승률: 0%
- 일일 누적 손익: -7,745,000원 (12번째 거래까지 확인)
- 원인: 박스권 장세(819~835 왕복)에서 스퀴즈 해제 후 양방향 반복 진입
- 긴급: 11:14:59 숏(826.30, stop=830.09) 진입 후 11:24:02 키움 연결 끊김(-106)
  → 포지션 미청산 여부 HTS에서 수동 확인 필요

### 발견된 버그 / 수정사항

1. **파라미터 불일치 발견**: backtest/engine.py 기본값(ema=200, look=10, stop=2.0)과
   실거래 config.yaml(ema=100, look=5, stop=3.0)이 달랐음.
   스윕 미실행 상태에서 임의 파라미터로 실거래 중이었음.

2. **신규 파일 생성**:
   - `kiwoom/realtime_5min.py`: RealtimeHandler5Min (5분 경계 QTimer 타이머)
   - `config_5min.yaml`: 5분봉 최적 파라미터 설정
   - `main_5min.py`: 5분봉 자동매매 진입점
   - `.claude/commands/trade-summary.md`: 거래 일지 커스텀 Skill
   - `.claude/commands/save-session.md`: 세션 저장 커스텀 Skill
   - `docs/brando_sweep_results.md`: 1분봉 스윕 결과
   - `docs/brando_sweep_5min.md`: 5분봉 스윕 결과

### 다음 세션 TODO

- [ ] config.yaml mom_lookback 5 → 3 변경 검토 (백테스트 최적값)
- [ ] 박스권 필터 추가 검토 (ADX, ATR 임계값 — 박스권에서 진입 억제)
- [ ] 3월물 만기(2026-03-13) 후 future_code 6월물(A0166000 예정)로 교체
- [ ] max_daily_loss 테스트용 10,000,000 → 실거래용 500,000 복원
- [ ] logging.level DEBUG → INFO 복원 (로그 파일 정리)
- [ ] 5분봉 모드 실거래 테스트 (main_5min.py)
- [ ] /trade-summary 실행하여 오늘 거래 내역 docs/trade-history.md에 기록

### 미해결 질문

- 11:24 연결 끊김 시점의 숏 포지션(826.30) 실제 청산 여부
- 5분봉 모드에서 look=10 vs look=3 중 어느 것이 실거래에서 더 안정적인가
- 박스권 필터 방식 선택: ADX < 20 필터 vs ATR 임계값 필터
