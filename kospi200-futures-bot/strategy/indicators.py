"""
기술적 지표 계산 모듈.

구현 지표:
- Bollinger Bands (BB)
- Keltner Channel (KC)
- Squeeze Momentum (LazyBear/John Carter 방식)
- Moving Average (SMA)
- ATR (Average True Range)

모든 함수는 pandas Series/DataFrame을 입력받아 Series/DataFrame을 반환한다.
TradingView Squeeze Momentum Indicator [LazyBear] 와 동일한 로직 적용.
"""

import numpy as np
import pandas as pd


# ------------------------------------------------------------------ #
# Bollinger Bands
# ------------------------------------------------------------------ #
def bollinger_bands(close: pd.Series, length: int = 20, mult: float = 2.0) -> pd.DataFrame:
    """
    Returns:
        DataFrame with columns: bb_mid, bb_upper, bb_lower
    """
    mid   = close.rolling(length).mean()
    std   = close.rolling(length).std(ddof=0)
    upper = mid + mult * std
    lower = mid - mult * std
    return pd.DataFrame({"bb_mid": mid, "bb_upper": upper, "bb_lower": lower})


# ------------------------------------------------------------------ #
# True Range / ATR
# ------------------------------------------------------------------ #
def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    tr = true_range(high, low, close)
    return tr.rolling(length).mean()


# ------------------------------------------------------------------ #
# Keltner Channel
# ------------------------------------------------------------------ #
def keltner_channel(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    length: int = 20,
    mult: float = 1.5,
) -> pd.DataFrame:
    """
    Keltner Channel: 중심선 = EMA(close), 밴드 = EMA ± mult × ATR(true range)
    Returns:
        DataFrame with columns: kc_mid, kc_upper, kc_lower
    """
    mid   = close.ewm(span=length, adjust=False).mean()
    _atr  = true_range(high, low, close).rolling(length).mean()
    upper = mid + mult * _atr
    lower = mid - mult * _atr
    return pd.DataFrame({"kc_mid": mid, "kc_upper": upper, "kc_lower": lower})


# ------------------------------------------------------------------ #
# Moving Average
# ------------------------------------------------------------------ #
def moving_average(close: pd.Series, fast: int = 5, slow: int = 20) -> pd.DataFrame:
    """
    Returns:
        DataFrame with columns: ma_fast, ma_slow
    """
    return pd.DataFrame({
        "ma_fast": close.rolling(fast).mean(),
        "ma_slow": close.rolling(slow).mean(),
    })


# ------------------------------------------------------------------ #
# Linear Regression (단일 값)
# ------------------------------------------------------------------ #
def _linreg_value(arr) -> float:
    """롤링 윈도우 배열의 마지막 점에 대한 선형회귀 예측값 반환. (raw=True 호환)"""
    y = np.asarray(arr, dtype=float)
    n = len(y)
    if n < 2:
        return np.nan
    mask = ~np.isnan(y)
    if mask.sum() < 2:
        return np.nan
    x = np.arange(n, dtype=float)
    coeffs = np.polyfit(x[mask], y[mask], 1)
    return float(np.polyval(coeffs, float(n - 1)))


def linreg(series: pd.Series, length: int) -> pd.Series:
    """롤링 선형회귀의 마지막 점 값 (TradingView linreg 동일). raw=True로 속도 최적화."""
    return series.rolling(length).apply(_linreg_value, raw=True)


# ------------------------------------------------------------------ #
# Squeeze Momentum (LazyBear 방식)
# ------------------------------------------------------------------ #
def squeeze_momentum(
    df: pd.DataFrame,
    bb_length: int = 20,
    bb_mult: float = 2.0,
    kc_length: int = 20,
    kc_mult: float = 1.5,
) -> pd.DataFrame:
    """
    Squeeze Momentum Indicator (LazyBear / John Carter 방식).

    Args:
        df: OHLCV DataFrame (컬럼: open, high, low, close, volume)

    Returns:
        DataFrame with columns:
          - squeeze_on   : bool, BB가 KC 안에 있으면 True (저변동성 압축)
          - squeeze_off  : bool, BB가 KC 밖으로 나오면 True (변동성 폭발)
          - momentum     : float, 선형회귀 모멘텀 값 (양수=상승, 음수=하락)
          - mom_increasing: bool, 전 봉 대비 모멘텀 증가 여부

    TradingView 동일 로직:
      momentum = linreg(source - avg(avg(highest(h,KC), lowest(l,KC)), SMA(close, KC)), length, 0)
      where source = close - avg(avg(highest(h, BB), lowest(l, BB)), SMA(close, BB))
    """
    high  = df["high"]
    low   = df["low"]
    close = df["close"]

    # --- Bollinger Bands ---
    bb = bollinger_bands(close, bb_length, bb_mult)

    # --- Keltner Channel ---
    kc = keltner_channel(high, low, close, kc_length, kc_mult)

    # --- Squeeze 상태 ---
    squeeze_on  = (bb["bb_lower"] > kc["kc_lower"]) & (bb["bb_upper"] < kc["kc_upper"])
    squeeze_off = ~squeeze_on

    # --- 모멘텀 계산 (LazyBear 방식) ---
    # delta = close - midpoint
    # midpoint = (highest_high + lowest_low) / 2 의 평균과 MA 평균
    highest_h = high.rolling(kc_length).max()
    lowest_l  = low.rolling(kc_length).min()
    kc_mid_hl = (highest_h + lowest_l) / 2
    kc_sma    = close.rolling(kc_length).mean()
    delta     = close - (kc_mid_hl + kc_sma) / 2

    momentum = linreg(delta, kc_length)
    mom_increasing = momentum > momentum.shift(1)

    return pd.DataFrame({
        "squeeze_on":    squeeze_on,
        "squeeze_off":   squeeze_off,
        "momentum":      momentum,
        "mom_increasing": mom_increasing,
    }, index=df.index)
