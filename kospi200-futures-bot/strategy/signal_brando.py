"""
브랜도(Brando) 매매법 신호 생성 모듈.

진입 조건:
  1. EMA 200 기준 추세 확인 (가격 > EMA200 → 상승 추세, 가격 < EMA200 → 하락 추세)
  2. Squeeze OFF 상태 (흰색 원, 시세 구간)
  3. 모멘텀이 직전 스퀴즈 ON 구간의 고점(롱) / 저점(숏)을 돌파

청산 조건:
  - 모멘텀 연한색(감소) 봉이 2봉 연속 → 힘이 빠지는 신호
    · 롱: mom_increasing = False 2봉 연속
    · 숏: mom_increasing = True  2봉 연속 (음수 모멘텀이 약해지는 방향)
"""

from typing import Optional

import pandas as pd

from .indicators import ema, squeeze_momentum


def generate_signal_brando(
    df: pd.DataFrame,
    current_position: Optional[str],
    ema_length: int = 200,
    bb_length: int = 20,
    bb_mult: float = 2.0,
    kc_length: int = 20,
    kc_mult: float = 1.5,
    mom_lookback: int = 10,
) -> Optional[str]:
    """
    브랜도 매매법 기반 신호를 생성한다.

    Args:
        df            : 갭 보정 OHLCV DataFrame. 최소 ema_length + 5 행 필요.
        current_position : 현재 포지션 ('long' / 'short' / None)
        ema_length    : 추세 확인용 EMA 기간 (기본 200)
        mom_lookback  : 모멘텀 돌파 기준 탐색 봉 수 (기본 10)

    Returns:
        'long' / 'short' / 'exit' / None
    """
    min_len = max(ema_length, bb_length, kc_length) + 5
    if len(df) < min_len:
        return None

    sq  = squeeze_momentum(df, bb_length, bb_mult, kc_length, kc_mult)
    ema200 = ema(df["close"], ema_length)

    curr     = sq.iloc[-1]
    prev     = sq.iloc[-2]
    prev2    = sq.iloc[-3]

    curr_close = df["close"].iloc[-1]
    curr_ema   = ema200.iloc[-1]

    if pd.isna(curr["momentum"]) or pd.isna(curr_ema):
        return None

    # ---- 청산 우선 ----
    if current_position == "long":
        # 롱 청산: 모멘텀 감소(연한색) 2봉 연속
        if not curr["mom_increasing"] and not prev["mom_increasing"]:
            return "exit"

    elif current_position == "short":
        # 숏 청산: 음수 모멘텀이 약해지는 방향(= mom_increasing) 2봉 연속
        if curr["mom_increasing"] and prev["mom_increasing"]:
            return "exit"

    # ---- 신규 진입 ----
    if current_position is None:
        # Squeeze OFF 상태여야 함 (흰색 원)
        if curr["squeeze_on"]:
            return None

        # EMA 200 추세
        trend_up = curr_close > curr_ema
        trend_dn = curr_close < curr_ema

        # 직전 squeeze ON 구간의 모멘텀 고점/저점 (동적 수평선)
        mom_series = sq["momentum"].iloc[-(mom_lookback + 2):-1]
        sq_on_series = sq["squeeze_on"].iloc[-(mom_lookback + 2):-1]

        # squeeze ON 구간의 모멘텀만 추출, 없으면 전체 구간 사용
        sq_on_mom = mom_series[sq_on_series]
        ref_mom = sq_on_mom if not sq_on_mom.empty else mom_series

        prev_peak  = float(ref_mom.max())
        prev_trough = float(ref_mom.min())

        curr_mom = float(curr["momentum"])

        if trend_up and curr_mom > 0 and curr_mom > prev_peak:
            return "long"
        if trend_dn and curr_mom < 0 and curr_mom < prev_trough:
            return "short"

    return None
