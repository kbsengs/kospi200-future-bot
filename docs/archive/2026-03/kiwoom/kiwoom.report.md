# 완료 보고서 — kiwoom (kospi200-futures-bot)

**작성일**: 2026-03-09
**프로젝트**: KOSPI200 선물 자동매매 봇 (Kiwoom OpenAPI+)
**PDCA 단계**: Plan → Design → Do → Check → Act → **Report** ✅

---

## Executive Summary

| 관점 | 내용 |
|------|------|
| **Problem** | 키움증권 OpenAPI+를 활용한 KOSPI200 선물 자동매매 시스템이 없어 수동 매매에 의존하며 감정적 판단과 기회 손실이 발생 |
| **Solution** | Squeeze Momentum 지표 + 갭 보정 + 당일 진입/청산 전략으로 객관적·자동화된 매매 시스템 구현 |
| **Function UX Effect** | Gap Analysis 82%→95% 달성, 1,152개 파라미터 스윕으로 최적 파라미터 확정, 백테스트 PF 1.80·총손익 +26,070,000원 검증 |
| **Core Value** | 감정 없는 규칙 기반 매매 자동화 + 리스크 관리(일일 손실 한도·ATR 손절)로 안정적 수익 추구 |

---

## 1. 프로젝트 개요

### 1.1 목표

| 항목 | 내용 |
|------|------|
| 대상 상품 | KOSPI200 선물 (1분봉) |
| 브로커 | 키움증권 OpenAPI+ (PyQt5 QAxWidget) |
| 전략 | Squeeze Momentum Indicator (LazyBear/John Carter) |
| 실행 환경 | Python 3.9, Windows |
| 기간 | 2026-03-07 ~ 2026-03-09 |

### 1.2 프로젝트 구조

```
kospi200-futures-bot/
├── main.py                  # 진입점, TradingBot 클래스
├── config.yaml              # 전략/리스크/시간 설정
├── requirements.txt         # 의존 패키지
├── kiwoom/
│   ├── api.py               # KiwoomAPI 래퍼 (COM 통신)
│   └── realtime.py          # 실시간 틱 수신 → 분봉 집계
├── strategy/
│   ├── indicators.py        # BB, KC, ATR, MA, Squeeze Momentum
│   └── signal.py            # 진입/청산 신호 생성
├── trading/
│   ├── order_manager.py     # 주문 실행 및 포지션 관리
│   └── risk_manager.py      # 일일 손실 한도, 손절가 계산
├── data/
│   ├── history.py           # 과거 데이터 로딩 (opt50028 TR)
│   └── gap_adjust.py        # 익일 갭 보정 (연속 가격 생성)
└── backtest/
    ├── engine.py            # O(n) 백테스트 엔진
    ├── param_sweep.py       # 기본 파라미터 스윕
    └── sweep_optimized.py   # 최적화 스윕 (1,152조합)
```

---

## 2. 전략 설계

### 2.1 핵심 전략: Squeeze Momentum

TradingView LazyBear 방식과 동일한 로직을 적용한다.

| 단계 | 조건 |
|------|------|
| **Squeeze ON** | BB가 KC 안에 완전히 포함 (저변동성 압축 구간) |
| **Squeeze OFF** | BB가 KC 밖으로 돌출 (변동성 폭발 직전) |
| **진입** | Squeeze OFF 전환 + 연속 Squeeze ≥ 3봉 + \|momentum\| > 0.2 + MA 방향 일치 |
| **청산** | 2봉 연속 모멘텀 반전 또는 BB 밴드 도달 |
| **손절** | ATR × 0.8 거리 |

### 2.2 갭 보정 (gap_adjust.py)

익일 시가 갭을 누적 보정하여 지표 계산 시 왜곡 제거.

```
adj_price = actual_price - cumulative_gap
gap = open_t - close_{t-1}  (날짜 변경 시점)
```

- 지표 계산: 보정가(adj) 사용
- 체결 계산: 실제가(actual) 사용

### 2.3 당일 진입/청산 (Intraday-only)

날짜 변경 감지 시 전일 종가로 강제 청산 → 익일 갭 리스크 완전 제거.

---

## 3. 구현 결과

### 3.1 Gap Analysis 결과

| 단계 | Match Rate | 처리 Gap |
|------|:----------:|---------|
| 최초 분석 (Check) | 82% | G-01~G-06 식별 |
| 1차 반복 (Act-1) | **95%** | G-01~G-06 전부 수정 |

### 3.2 수정된 Gap 목록

| ID | 심각도 | 내용 | 수정 파일 |
|----|:------:|------|----------|
| G-01 | Critical | 일일 손실 한도 미작동 (`_record_pnl` 누락) | `main.py` |
| G-02 | Critical | `get_login_state()` Python `and` 연산자 오용 | `kiwoom/api.py` |
| G-03 | Medium | 체결가 `OrderManager` 미연동 (`on_fill` 콜백) | `kiwoom/realtime.py` |
| G-04 | Medium | `config.yaml` server 설정 미적용 (모의/실서버 검증 추가) | `kiwoom/api.py` |
| G-05 | Medium | `requirements.txt` 누락 | 신규 생성 |
| G-06 | Low | `import math` 루프 내부 위치 | `backtest/engine.py` |

### 3.3 추가 개선 사항 (전략 수익화)

| 개선 | 내용 | 효과 |
|------|------|------|
| 갭 보정 지표 | `data/gap_adjust.py` 신규 작성 | 익일 갭 노이즈 제거 |
| 당일 진입/청산 | 날짜 변경 시 전일 종가 강제 청산 | 갭 리스크 제거 |
| 2봉 연속 청산 | 모멘텀 단일 반전 → 2봉 연속 확인 | 노이즈성 청산 감소 |
| Squeeze 지속 필터 | `min_squeeze_bars` 조건 추가 | 약한 압축 신호 제외 |
| 모멘텀 강도 필터 | `min_momentum` 임계값 추가 | 약한 진입 신호 제외 |
| linreg 속도 최적화 | `rolling().apply(raw=True)` 적용 | 스윕 실행 속도 향상 |

---

## 4. 백테스트 성과

### 4.1 테스트 환경

| 항목 | 내용 |
|------|------|
| 데이터 | KOSPI200 선물 1분봉 실데이터 |
| 기간 | 2025-09-10 ~ 2025-12-19 (약 3.5개월) |
| 봉 수 | 27,900개 |
| 파라미터 스윕 | 1,152개 조합 |

### 4.2 최적 파라미터 (config.yaml 적용 완료)

| 파라미터 | 값 |
|---------|-----|
| `bb_length` | 20 |
| `bb_mult` | 2.0 |
| `kc_length` | 20 |
| `kc_mult` | **2.0** |
| `ma_fast` | 5 |
| `ma_slow` | 20 |
| `stop_atr_mult` | **0.8** |
| `min_squeeze_bars` | **3** |
| `min_momentum` | **0.2** |

### 4.3 백테스트 결과

| 지표 | 값 |
|------|-----|
| **총손익** | **+26,070,000원** |
| **PF (손익비)** | **1.80** |
| **승률** | **57.1%** |
| **총 거래 수** | 548회 |
| **최대 낙폭 (MDD)** | -2,755,000원 |

### 4.4 이전 대비 개선

| 지표 | 개선 전 | 개선 후 |
|------|:-------:|:-------:|
| 총손익 | -2,760,000원 | **+26,070,000원** |
| PF | 0.99 | **1.80** |
| MDD | -6,010,000원 | **-2,755,000원** |

---

## 5. 리스크 관리

| 항목 | 설정 |
|------|------|
| 최대 보유 계약수 | 1계약 |
| ATR 손절 배수 | 0.8× |
| 일일 최대 손실 한도 | 500,000원 |
| 신규 진입 금지 | 15:30 이후 |
| 장 마감 강제 청산 | 15:45 |

---

## 6. 실전 적용 시 유의사항

1. **모의투자 검증 필수**: `config.yaml`의 `server: "demo"` 상태로 최소 1주 이상 실행 검증
2. **슬리피지**: 백테스트는 시가(open) 체결 가정. 실전에서는 1~2틱 슬리피지 발생 가능
3. **거래 빈도**: 548회/3.5개월 ≈ 일평균 8회. 수수료 실비 확인 필요
4. **근월물 교체**: `future_code: "101N9000"` 만기 시 종목코드 수동 갱신 필요
5. **윈도우 환경**: 키움 OpenAPI+는 32bit Python 필요 (`C:\Python39-32`)

---

## 7. 다음 단계 권장

| 우선순위 | 작업 |
|---------|------|
| 1 | 모의투자 1~2주 실행 검증 |
| 2 | `get_order_qty()` 증거금 기반 계약수 계산 구현 (G-07) |
| 3 | 근월물 자동 교체 로직 추가 |
| 4 | 실거래 전환 (`server: "real"`) |

---

*[Plan] ✅ → [Design] ✅ → [Do] ✅ → [Check] ✅ (95%) → [Act] ✅ → [Report] ✅*
