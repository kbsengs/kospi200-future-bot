"""
진입/청산 신호 생성 모듈 (갭 보정 + 개선된 필터 적용).

신호 타입:
  'long'  - 롱 진입
  'short' - 숏 진입
  'exit'  - 현재 포지션 청산
  None    - 아무 신호 없음

진입 조건 (v2):
  1. Squeeze ON→OFF 전환
  2. Squeeze ON 상태가 min_squeeze_bars 봉 이상 연속 지속 (압축 강도 조건)
  3. |momentum| > min_momentum (약한 모멘텀 제외)
  4. 모멘텀 방향과 MA 크로스 일치

청산 조건 (v2):
  - 모멘텀 2봉 연속 반전 (노이즈 1봉 무시)
  - 가격이 BB 반대편 도달

df 는 갭 보정된 OHLCV를 전달받는 것을 권장한다.
  from data.gap_adjust import make_indicator_df
  signal = generate_signal(make_indicator_df(raw_df), ...)
"""

from typing import Optional

import pandas as pd

from .indicators import bollinger_bands, moving_average, squeeze_momentum


def generate_signal(
    df: pd.DataFrame,
    current_position: Optional[str],
    bb_length: int = 20,
    bb_mult: float = 2.0,
    kc_length: int = 20,
    kc_mult: float = 1.5,
    ma_fast: int = 5,
    ma_slow: int = 20,
    min_squeeze_bars: int = 5,
    min_momentum: float = 0.3,
) -> Optional[str]:
    """
    갭 보정된 OHLCV DataFrame을 기반으로 신호를 생성한다.

    Args:
        df               : 갭 보정 OHLCV DataFrame. 최소 max(lengths) + 3 행 필요.
        current_position : 현재 보유 포지션 ('long' / 'short' / None)
        min_squeeze_bars : 진입 조건 — Squeeze ON 최소 연속 봉 수 (기본 5)
        min_momentum     : 진입 조건 — |momentum| 최솟값 (기본 0.3)

    Returns:
        'long' / 'short' / 'exit' / None
    """
    min_len = max(bb_length, kc_length, ma_slow) + 3   # 2봉 exit 확인용 +3
    if len(df) < min_len:
        return None

    sq  = squeeze_momentum(df, bb_length, bb_mult, kc_length, kc_mult)
    bb  = bollinger_bands(df["close"], bb_length, bb_mult)
    ma  = moving_average(df["close"], ma_fast, ma_slow)

    # 최근 3봉 (2봉 연속 모멘텀 확인)
    prev2 = sq.iloc[-3]
    prev  = sq.iloc[-2]
    curr  = sq.iloc[-1]

    curr_bb    = bb.iloc[-1]
    curr_ma    = ma.iloc[-1]
    curr_close = df["close"].iloc[-1]

    # ---- 청산 우선 (2봉 연속 모멘텀 반전 → 노이즈 1봉 무시) ----
    if current_position == "long":
        momentum_reversal = (prev["momentum"] < 0) and (curr["momentum"] < 0)
        bb_target_hit     = curr_close >= curr_bb["bb_upper"]
        if momentum_reversal or bb_target_hit:
            return "exit"

    elif current_position == "short":
        momentum_reversal = (prev["momentum"] > 0) and (curr["momentum"] > 0)
        bb_target_hit     = curr_close <= curr_bb["bb_lower"]
        if momentum_reversal or bb_target_hit:
            return "exit"

    # ---- 신규 진입 ----
    if current_position is None:
        squeeze_fired = prev["squeeze_on"] and not curr["squeeze_on"]

        if squeeze_fired:
            # Squeeze 압축 지속 시간 확인 (prev 포함 역방향 카운트)
            sq_on = sq["squeeze_on"]
            consecutive = 0
            for j in range(len(sq_on) - 2, -1, -1):
                if sq_on.iloc[j]:
                    consecutive += 1
                else:
                    break

            if consecutive >= min_squeeze_bars:
                mom = curr["momentum"]
                if mom > min_momentum and curr_ma["ma_fast"] > curr_ma["ma_slow"]:
                    return "long"
                if mom < -min_momentum and curr_ma["ma_fast"] < curr_ma["ma_slow"]:
                    return "short"

    return None
