# Gap Analysis — kiwoom (kospi200-futures-bot)

**Date**: 2026-03-07
**Phase**: Check
**Match Rate**: 82%

---

## 1. 분석 요약

| 항목 | 내용 |
|------|------|
| 분석 대상 | kospi200-futures-bot (Kiwoom OpenAPI+ 자동매매 봇) |
| 총 파일 수 | 13개 Python 파일 + 1개 YAML |
| Match Rate | **82%** |
| 판정 | ⚠️ 개선 필요 (목표: 90% 이상) |

---

## 2. 구현 완료 항목

| 모듈 | 파일 | 완성도 | 비고 |
|------|------|:------:|------|
| Kiwoom API 래퍼 | `kiwoom/api.py` | 90% | 로그인 상태 판별 로직 버그 |
| 실시간 수신 | `kiwoom/realtime.py` | 85% | realtype 필터 검증 필요 |
| 지표 계산 | `strategy/indicators.py` | 100% | Squeeze, BB, KC, ATR, MA 완비 |
| 신호 생성 | `strategy/signal.py` | 100% | 진입/청산 조건 완비 |
| 주문 관리 | `trading/order_manager.py` | 90% | entry_price 미연동 (P&L 기록용) |
| 리스크 관리 | `trading/risk_manager.py` | 70% | daily_pnl 기록 미호출로 한도 기능 불작동 |
| 데이터 관리 | `data/history.py` | 95% | 완비 |
| 백테스트 엔진 | `backtest/engine.py` | 95% | import 위치 경미한 문제 |
| 파라미터 스윕 | `backtest/param_sweep.py` | 100% | 완비 |
| 메인 진입점 | `main.py` | 85% | 일일 손실 한도 미작동, balance=0 고정 |
| 설정 파일 | `config.yaml` | 90% | server 모드 미적용 |
| 연결 테스트 | `test_connection.py` | 100% | 완비 |
| 지표 검증 | `verify_indicators.py` | 100% | 완비 |

---

## 3. Gap 목록

### [Critical] G-01: 일일 손실 한도 기능 불작동

**파일**: `main.py`, `trading/risk_manager.py`

`RiskManager.record_trade_pnl()`이 구현되어 있으나 `main.py`의 청산 흐름 어디에서도 호출되지 않는다.
결과적으로 `_daily_pnl`은 항상 0이고 `is_trading_halted`는 절대 True가 되지 않아 일일 최대 손실 한도(`max_daily_loss: 500,000원`) 기능이 완전히 무력화된다.

```python
# main.py _on_bar_close() — 청산 후 손익 기록 누락
if signal == "exit":
    self.order_mgr.exit_position(reason="signal")
    # TODO: pnl 계산 후 self.risk_mgr.record_trade_pnl(pnl) 호출 필요
```

**수정 방향**: `exit_position()` 후 진입가·청산가 기반 PnL을 계산하여 `record_trade_pnl()` 호출.

---

### [Critical] G-02: `get_login_state()` 반환 로직 버그

**파일**: `kiwoom/api.py:51-52`

```python
def get_login_state(self) -> int:
    return self.dynamicCall("GetLoginInfo(QString)", "GetServerGubun") and \
           self.dynamicCall("GetConnectState()")
```

`GetServerGubun`은 `"0"` 또는 `"1"` 문자열을 반환한다. Python에서 비어 있지 않은 문자열은 항상 truthy이므로 `"0" and ConnectState()` 는 항상 `ConnectState()`를 반환한다. 모의투자("0")와 실서버("1")를 구분하는 의도가 전혀 반영되지 않으며, `login()` 반환값 `== 1`과 맞물려 예상치 못한 동작을 유발할 수 있다.

**수정 방향**:
```python
def get_login_state(self) -> int:
    return self.dynamicCall("GetConnectState()")
```

---

### [Medium] G-03: 체결가(entry_price) OrderManager 미연동

**파일**: `kiwoom/realtime.py:108-117`, `trading/order_manager.py:113`

`RealtimeHandler._on_chejan()`에서 FID 910으로 체결가를 추출하고 로그를 출력하지만 `OrderManager.update_fill_price()`를 호출하지 않는다. 결과적으로 `Position.entry_price`는 항상 `0.0`으로 유지된다.
현재 손절가는 진입 신호 시점의 `current_price`로 계산하므로 손절 로직 자체는 작동하나, P&L 계산 및 향후 기능 확장 시 문제가 된다.

**수정 방향**: `RealtimeHandler`에 `OrderManager` 참조를 추가하고 체결 이벤트에서 `update_fill_price()` 호출.

---

### [Medium] G-04: config `server` 설정 미적용

**파일**: `kiwoom/api.py:29`, `config.yaml:4`

`config.yaml`에 `server: "demo"` 설정이 있으나 `KiwoomAPI.__init__`에서 사용되지 않는다. 키움 API는 `SetServer()` 호출로 모의투자/실거래를 전환할 수 있으나 현재 미구현.

---

### [Medium] G-05: `requirements.txt` 누락

의존 패키지(`PyQt5`, `loguru`, `pandas`, `numpy`, `pyyaml`)가 어디에도 명시되지 않아 신규 환경 구성이 불가능하다.

---

### [Low] G-06: `import math` 루프 내부 위치

**파일**: `backtest/engine.py:178`

```python
for i in range(min_idx, len(df)):
    ...
    import math   # 루프마다 실행됨 (실제 성능 영향은 미미하나 관례 위반)
```

파일 상단으로 이동 필요.

---

### [Low] G-07: `get_order_qty()` balance 미활용

**파일**: `trading/risk_manager.py:64-71`, `main.py:161`

`get_order_qty(balance=0, ...)` 호출 시 balance가 항상 0이며 내부에서도 단순히 `max_contracts`를 반환한다. 실거래 시 증거금 기반 계약수 계산 로직 필요.

---

## 4. 점수 산정

| 구분 | 항목 수 | 배점 | 취득 |
|------|:-------:|:----:|:----:|
| Critical Gap | 2 | -6점 each | -12 |
| Medium Gap | 3 | -2점 each | -6 |
| Low Gap | 2 | -0점 (감점 없음) | 0 |
| **합계** | | **100** | **82** |

**Match Rate: 82%** → 90% 미만 → 개선 반복(Act) 권장

---

## 5. 개선 우선순위

1. **G-01** — 일일 손실 한도 작동 복구 (리스크 관리 핵심 기능)
2. **G-02** — 로그인 상태 판별 버그 수정 (신뢰성)
3. **G-05** — requirements.txt 생성 (운영 필수)
4. **G-03** — 체결가 연동 (P&L 추적)
5. **G-04** — 서버 모드 설정 적용
6. **G-06** — import 위치 정리

---

## 6. 다음 단계

Match Rate 82% — `/pdca iterate kiwoom` 으로 자동 개선 실행을 권장한다.
