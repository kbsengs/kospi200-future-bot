"""
갭 보정 모듈.

전일 종가 대비 당일 시가의 갭을 누적 제거하여 연속(Continuous) 가격 시리즈를 만든다.
지표 계산(BB, KC, Squeeze, MA, ATR)에는 갭 보정 가격을 사용하고,
실제 주문 체결가·손익 계산은 원본 가격을 유지한다.

갭 보정 원리:
  gap_i = open_i - close_{i-1}   (새 거래일 첫봉에서만 발생)
  cumulative_gap += gap_i
  adj_price = real_price - cumulative_gap   → 연속 가격 형성
"""

import pandas as pd


def gap_adjust(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    """
    OHLCV DataFrame에 갭 보정 가격 컬럼(adj_*)을 추가한다.

    Args:
        df       : 시간 오름차순 OHLCV DataFrame.
                   'open', 'high', 'low', 'close', 'volume' 컬럼 필수.
        date_col : 날짜 구분에 사용할 컬럼명 (기본 'date').

    Returns:
        원본 컬럼 + adj_open / adj_high / adj_low / adj_close 가 추가된 DataFrame.
    """
    result = df.copy()

    try:
        dates = pd.to_datetime(result[date_col]).dt.date
    except Exception:
        dates = result[date_col].astype(str)

    opens  = result["open"].to_numpy(dtype=float)
    closes = result["close"].to_numpy(dtype=float)

    cumulative_gap = 0.0
    gap_series = []
    prev_close = None
    prev_date  = None

    for i in range(len(result)):
        curr_date = dates.iloc[i]
        if prev_date is not None and curr_date != prev_date:
            # 새 거래일 첫봉 → 갭 누적
            cumulative_gap += opens[i] - prev_close
        gap_series.append(cumulative_gap)
        prev_close = closes[i]
        prev_date  = curr_date

    gap_s = pd.Series(gap_series, index=result.index)
    result["adj_open"]  = (result["open"]  - gap_s).round(2)
    result["adj_high"]  = (result["high"]  - gap_s).round(2)
    result["adj_low"]   = (result["low"]   - gap_s).round(2)
    result["adj_close"] = (result["close"] - gap_s).round(2)

    return result


def make_indicator_df(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    """
    갭 보정 가격으로 지표 계산용 DataFrame을 반환한다.
    open/high/low/close → adj_* 값으로 교체, volume 유지.
    """
    adj = gap_adjust(df, date_col)
    ind = adj[["adj_open", "adj_high", "adj_low", "adj_close", "volume"]].copy()
    ind.columns = ["open", "high", "low", "close", "volume"]
    ind.index = df.index
    return ind
