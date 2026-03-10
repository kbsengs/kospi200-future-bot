"""
백테스트 엔진.

CSV 또는 DataFrame으로 과거 데이터를 입력받아
Squeeze Momentum 전략 또는 브랜도 전략을 시뮬레이션하고 성과 지표를 출력한다.

실행 예시:
    python -m backtest.engine --csv data/sample.csv
    python -m backtest.engine --csv data/sample.csv --strategy brando
"""

import argparse
import math
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import numpy as np
from loguru import logger

from strategy.indicators import atr, bollinger_bands, ema, moving_average, squeeze_momentum


@dataclass
class Trade:
    direction: str
    entry_idx: int
    entry_price: float
    stop_price: float = 0.0
    exit_idx: int = 0
    exit_price: float = 0.0
    pnl: float = 0.0
    exit_reason: str = ""


@dataclass
class BacktestResult:
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    strategy_name: str = ""

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def win_trades(self) -> int:
        return sum(1 for t in self.trades if t.pnl > 0)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        return self.win_trades / self.total_trades * 100

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.pnl for t in self.trades if t.pnl > 0)
        gross_loss   = abs(sum(t.pnl for t in self.trades if t.pnl < 0))
        return gross_profit / gross_loss if gross_loss > 0 else float("inf")

    @property
    def max_drawdown(self) -> float:
        """최대 낙폭 (원화 절대값). 초기 자본 0 기준."""
        if not self.equity_curve:
            return 0.0
        eq = np.array([0.0] + self.equity_curve)
        peak = np.maximum.accumulate(eq)
        dd = eq - peak
        return float(dd.min())

    def print_summary(self):
        name = f"  [{self.strategy_name}] " if self.strategy_name else "  "
        print("\n" + "=" * 52)
        print(f"{name}백테스트 결과 요약")
        print("=" * 52)
        print(f"  총 거래 수    : {self.total_trades}")
        print(f"  승률          : {self.win_rate:.1f}%")
        print(f"  총 손익       : {self.total_pnl:,.0f}원")
        print(f"  손익비(PF)    : {self.profit_factor:.2f}")
        print(f"  최대 낙폭(MDD): {self.max_drawdown:,.0f}원")
        print("=" * 52 + "\n")


def _parse_time_col(df: pd.DataFrame):
    """
    'time' 컬럼(YYYYMMDDHHMI 형식)에서 날짜(YYYYMMDD)와 HHMM을 추출한다.
    Returns:
        dates : YYYYMMDD int 배열
        hhmms : HHMM int 배열 (예: 1530)
    """
    t = df["time"].astype(str).str.strip()
    # 길이가 12자리: YYYYMMDDHHMI → 앞 8자리 날짜, 뒤 4자리 HHMM
    dates = t.str[:8].astype(int).values
    hhmms = t.str[8:12].astype(int).values
    return dates, hhmms


class BacktestEngine:
    """
    봉 단위 백테스트 엔진.
    코스피200 선물 1계약 = 가격 × 250,000 포인트 가치.

    당일 청산:
      - 15:30 봉 종가에 청산 ('time' 컬럼이 있을 때)
      - 'time' 컬럼 없고 'date' 컬럼 있으면 날짜 변경 시 전일 종가로 청산
    """

    POINT_VALUE = 250_000  # 1포인트 = 250,000원
    EOD_HHMM    = 1530     # 당일 청산 시각 (15시 30분)

    def __init__(
        self,
        strategy: str = "squeeze",       # "squeeze" | "brando"
        bb_length: int = 20,
        bb_mult: float = 2.0,
        kc_length: int = 20,
        kc_mult: float = 1.5,
        # squeeze 전략 파라미터
        ma_fast: int = 5,
        ma_slow: int = 20,
        min_squeeze_bars: int = 5,
        min_momentum: float = 0.3,
        # brando 전략 파라미터
        ema_length: int = 200,
        mom_lookback: int = 10,
        # 공통
        stop_atr_mult: float = 2.0,
        atr_length: int = 14,
        max_contracts: int = 1,
        commission_per_contract: float = 5_000,
    ):
        self.strategy       = strategy
        self.bb_length      = bb_length
        self.bb_mult        = bb_mult
        self.kc_length      = kc_length
        self.kc_mult        = kc_mult
        self.ma_fast        = ma_fast
        self.ma_slow        = ma_slow
        self.min_squeeze_bars = min_squeeze_bars
        self.min_momentum     = min_momentum
        self.ema_length     = ema_length
        self.mom_lookback   = mom_lookback
        self.stop_atr_mult  = stop_atr_mult
        self.atr_length     = atr_length
        self.max_contracts  = max_contracts
        self.commission     = commission_per_contract

    def run(self, df: pd.DataFrame) -> BacktestResult:
        """
        O(n) 백테스트: 갭 보정 가격으로 지표 계산, 실제 가격으로 체결.

        Args:
            df: OHLCV DataFrame.
                'time' 컬럼(YYYYMMDDHHMI) 있으면 15:30 종가로 당일 청산.
                'date' 컬럼 있으면 날짜 변경 시 전일 종가로 청산.
        """
        from strategy.indicators import (
            bollinger_bands, keltner_channel, squeeze_momentum,
            moving_average, ema as calc_ema, atr as calc_atr,
        )
        from data.gap_adjust import make_indicator_df

        result = BacktestResult(strategy_name=self.strategy)

        # ---- 시간 정보 파싱 ----
        has_time = "time" in df.columns
        has_date = "date" in df.columns

        dates_arr = hhmms_arr = date_arr = None

        if has_time:
            dates_arr, hhmms_arr = _parse_time_col(df)
            date_arr = dates_arr   # 날짜 변경 감지용
        elif has_date:
            date_arr = pd.to_datetime(df["date"]).dt.date.values

        # ---- 갭 보정 ----
        if has_time:
            # time 컬럼을 date_col로 사용하기 위해 날짜 컬럼 임시 생성
            tmp = df.copy()
            tmp["_date"] = pd.to_datetime(df["time"].astype(str), format="%Y%m%d%H%M").dt.date
            ind_df = make_indicator_df(tmp, date_col="_date")
        elif has_date:
            ind_df = make_indicator_df(df, date_col="date")
        else:
            ind_df = df

        # ---- 지표 전체 사전 계산 ----
        sq   = squeeze_momentum(ind_df, self.bb_length, self.bb_mult, self.kc_length, self.kc_mult)
        bb   = bollinger_bands(ind_df["close"], self.bb_length, self.bb_mult)
        _atr = calc_atr(ind_df["high"], ind_df["low"], ind_df["close"], self.atr_length)

        squeeze_on_vals  = sq["squeeze_on"].values
        momentum_vals    = sq["momentum"].values
        mom_inc_vals     = sq["mom_increasing"].values
        bb_upper_vals    = bb["bb_upper"].values
        bb_lower_vals    = bb["bb_lower"].values
        atr_vals         = _atr.values
        ema200_vals      = calc_ema(ind_df["close"], self.ema_length).values

        if self.strategy == "squeeze":
            ma   = moving_average(ind_df["close"], self.ma_fast, self.ma_slow)
            ma_fast_vals = ma["ma_fast"].values
            ma_slow_vals = ma["ma_slow"].values

            # 연속 Squeeze ON 봉 수 사전 계산
            consecutive_squeeze = np.zeros(len(df), dtype=int)
            for i in range(len(df)):
                if squeeze_on_vals[i]:
                    consecutive_squeeze[i] = (consecutive_squeeze[i - 1] + 1) if i > 0 else 1
                else:
                    consecutive_squeeze[i] = 0

        close_vals = df["close"].values
        open_vals  = df["open"].values

        current_trade: Optional[Trade] = None
        equity = 0.0

        min_idx = max(self.bb_length, self.kc_length,
                      self.ma_slow if self.strategy == "squeeze" else 0,
                      self.ema_length if self.strategy == "brando" else 0,
                      self.atr_length) + self.mom_lookback + 5

        for i in range(min_idx, len(df)):
            cur_close = close_vals[i]

            # ---- 15:30 종가 청산 (당일 청산) ----
            if has_time and hhmms_arr is not None:
                if hhmms_arr[i] == self.EOD_HHMM and current_trade is not None:
                    current_trade = self._close_trade(
                        current_trade, i, cur_close, "eod_1530", result
                    )
                    equity += current_trade.pnl
                    result.equity_curve.append(equity)
                    current_trade = None
                    continue

            # ---- 날짜 변경 시 전일 종가 청산 (time 없고 date만 있을 때) ----
            elif has_date and date_arr is not None and i > 0 and date_arr[i] != date_arr[i - 1]:
                if current_trade is not None:
                    eod_price = close_vals[i - 1]
                    current_trade = self._close_trade(
                        current_trade, i - 1, eod_price, "eod", result
                    )
                    equity += current_trade.pnl
                    result.equity_curve.append(equity)
                    current_trade = None

            # ---- 손절 체크 ----
            if current_trade is not None and current_trade.stop_price > 0:
                stop_hit = (
                    (current_trade.direction == "long"  and cur_close <= current_trade.stop_price) or
                    (current_trade.direction == "short" and cur_close >= current_trade.stop_price)
                )
                if stop_hit:
                    current_trade = self._close_trade(
                        current_trade, i, cur_close, "stop_loss", result
                    )
                    equity += current_trade.pnl
                    result.equity_curve.append(equity)
                    current_trade = None
                    continue

            # ---- 신호 판단 ----
            curr_mom = momentum_vals[i]
            if math.isnan(curr_mom):
                continue

            signal = None

            if self.strategy == "squeeze":
                signal = self._signal_squeeze(
                    i, squeeze_on_vals, momentum_vals,
                    bb_upper_vals, bb_lower_vals,
                    ma_fast_vals, ma_slow_vals,
                    consecutive_squeeze, cur_close, current_trade,
                )
            else:
                signal = self._signal_brando(
                    i, squeeze_on_vals, momentum_vals, mom_inc_vals,
                    ema200_vals, cur_close, current_trade,
                )

            entry_price = open_vals[i]

            if signal == "exit" and current_trade is not None:
                current_trade = self._close_trade(
                    current_trade, i, entry_price, "signal", result
                )
                equity += current_trade.pnl
                result.equity_curve.append(equity)
                current_trade = None

            elif signal in ("long", "short") and current_trade is None:
                atr_val = atr_vals[i]
                if math.isnan(atr_val) or atr_val == 0:
                    atr_val = entry_price * 0.005
                dist   = atr_val * self.stop_atr_mult
                stop_p = entry_price - dist if signal == "long" else entry_price + dist

                current_trade = Trade(
                    direction=signal,
                    entry_idx=i,
                    entry_price=entry_price,
                    stop_price=stop_p,
                )
                logger.debug(f"[{i}] {signal} 진입 @ {entry_price:.2f} stop={stop_p:.2f}")

        # 미결 포지션 강제 청산
        if current_trade is not None:
            current_trade = self._close_trade(
                current_trade, len(df) - 1, close_vals[-1], "end_of_data", result
            )
            equity += current_trade.pnl
            result.equity_curve.append(equity)

        return result

    # ------------------------------------------------------------------ #
    # 전략별 신호 계산
    # ------------------------------------------------------------------ #

    def _signal_squeeze(
        self, i, squeeze_on, momentum, bb_upper, bb_lower,
        ma_fast, ma_slow, consecutive_squeeze, cur_close,
        current_trade: Optional[Trade],
    ) -> Optional[str]:
        """기존 Squeeze Momentum 전략 신호."""
        curr_mom = momentum[i]
        prev_mom = momentum[i - 1]

        if math.isnan(ma_fast[i]) or math.isnan(ma_slow[i]):
            return None

        if current_trade is not None:
            direction = current_trade.direction
            mom_reversal = (
                (direction == "long"  and not math.isnan(prev_mom) and prev_mom < 0 and curr_mom < 0) or
                (direction == "short" and not math.isnan(prev_mom) and prev_mom > 0 and curr_mom > 0)
            )
            bb_target = (
                (direction == "long"  and cur_close >= bb_upper[i]) or
                (direction == "short" and cur_close <= bb_lower[i])
            )
            if mom_reversal or bb_target:
                return "exit"
        else:
            squeeze_fired = squeeze_on[i - 1] and not squeeze_on[i]
            consec = int(consecutive_squeeze[i - 1])
            if squeeze_fired and consec >= self.min_squeeze_bars:
                if curr_mom > self.min_momentum and ma_fast[i] > ma_slow[i]:
                    return "long"
                elif curr_mom < -self.min_momentum and ma_fast[i] < ma_slow[i]:
                    return "short"
        return None

    def _signal_brando(
        self, i, squeeze_on, momentum, mom_increasing,
        ema200, cur_close,
        current_trade: Optional[Trade],
    ) -> Optional[str]:
        """브랜도 전략 신호."""
        curr_mom  = momentum[i]
        curr_inc  = mom_increasing[i]
        prev_inc  = mom_increasing[i - 1]

        if math.isnan(ema200[i]):
            return None

        if current_trade is not None:
            direction = current_trade.direction
            if direction == "long":
                # 롱 청산: 모멘텀 감소(연한색) 2봉 연속
                if not curr_inc and not prev_inc:
                    return "exit"
            elif direction == "short":
                # 숏 청산: 음수 모멘텀이 약해지는 방향 2봉 연속
                if curr_inc and prev_inc:
                    return "exit"
        else:
            # Squeeze OFF 상태여야 진입 가능
            if squeeze_on[i]:
                return None

            trend_up = cur_close > ema200[i]
            trend_dn = cur_close < ema200[i]

            # 직전 squeeze ON 구간의 모멘텀 고점/저점 (동적 수평선)
            start = max(0, i - self.mom_lookback - 2)
            ref_mom_vals   = momentum[start:i]
            ref_sq_on_vals = squeeze_on[start:i]

            sq_mom = ref_mom_vals[ref_sq_on_vals]
            if len(sq_mom) == 0:
                sq_mom = ref_mom_vals

            valid = sq_mom[~np.isnan(sq_mom)]
            if len(valid) == 0:
                return None

            prev_peak   = float(valid.max())
            prev_trough = float(valid.min())

            if trend_up and curr_mom > 0 and curr_mom > prev_peak:
                return "long"
            if trend_dn and curr_mom < 0 and curr_mom < prev_trough:
                return "short"

        return None

    def _close_trade(
        self, trade: Trade, idx: int, price: float, reason: str,
        result: BacktestResult,
    ) -> Trade:
        trade.exit_idx    = idx
        trade.exit_price  = price
        trade.exit_reason = reason

        qty = self.max_contracts
        if trade.direction == "long":
            raw_pnl = (price - trade.entry_price) * self.POINT_VALUE * qty
        else:
            raw_pnl = (trade.entry_price - price) * self.POINT_VALUE * qty

        trade.pnl = raw_pnl - self.commission * 2 * qty
        result.trades.append(trade)
        logger.debug(
            f"[{idx}] {trade.direction} 청산 @ {price} pnl={trade.pnl:,.0f}원 reason={reason}"
        )
        return trade


# ------------------------------------------------------------------ #
# CLI 진입점
# ------------------------------------------------------------------ #
def main():
    parser = argparse.ArgumentParser(description="Squeeze Momentum 백테스트")
    parser.add_argument("--csv",      required=True, help="OHLCV CSV 파일 경로")
    parser.add_argument("--strategy", default="squeeze", choices=["squeeze", "brando"],
                        help="사용할 전략 (기본: squeeze)")
    parser.add_argument("--bb-length",   type=int,   default=20)
    parser.add_argument("--bb-mult",     type=float, default=2.0)
    parser.add_argument("--kc-length",   type=int,   default=20)
    parser.add_argument("--kc-mult",     type=float, default=1.5)
    parser.add_argument("--ma-fast",     type=int,   default=5)
    parser.add_argument("--ma-slow",     type=int,   default=20)
    parser.add_argument("--ema-length",  type=int,   default=200)
    parser.add_argument("--mom-lookback",type=int,   default=10)
    parser.add_argument("--stop-atr",    type=float, default=2.0)
    args = parser.parse_args()

    df = pd.read_csv(args.csv)
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float).abs()
    df["volume"] = df["volume"].astype(int).abs()

    engine = BacktestEngine(
        strategy=args.strategy,
        bb_length=args.bb_length,
        bb_mult=args.bb_mult,
        kc_length=args.kc_length,
        kc_mult=args.kc_mult,
        ma_fast=args.ma_fast,
        ma_slow=args.ma_slow,
        ema_length=args.ema_length,
        mom_lookback=args.mom_lookback,
        stop_atr_mult=args.stop_atr,
    )
    result = engine.run(df)
    result.print_summary()


if __name__ == "__main__":
    main()
