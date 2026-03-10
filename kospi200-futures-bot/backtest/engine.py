"""
백테스트 엔진.

CSV 또는 DataFrame으로 과거 데이터를 입력받아
Squeeze Momentum 전략을 시뮬레이션하고 성과 지표를 출력한다.

실행 예시:
    python -m backtest.engine --csv data/sample.csv
"""

import argparse
import math
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import numpy as np
from loguru import logger

from strategy.indicators import atr, bollinger_bands, moving_average, squeeze_momentum
from strategy.signal import generate_signal


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
        dd = eq - peak          # 항상 0 이하
        return float(dd.min())  # 가장 큰 손실액 (음수)


    def print_summary(self):
        print("\n" + "=" * 50)
        print("  백테스트 결과 요약")
        print("=" * 50)
        print(f"  총 거래 수    : {self.total_trades}")
        print(f"  승률          : {self.win_rate:.1f}%")
        print(f"  총 손익       : {self.total_pnl:,.0f}원")
        print(f"  손익비(PF)    : {self.profit_factor:.2f}")
        print(f"  최대 낙폭(MDD): {self.max_drawdown:,.0f}원")
        print("=" * 50 + "\n")


class BacktestEngine:
    """
    봉 단위 백테스트 엔진.
    코스피200 선물 1계약 = 가격 × 250,000 포인트 가치 (틱 단위 손익 적용 시 수정 필요).
    """

    POINT_VALUE = 250_000  # 1포인트 = 250,000원

    def __init__(
        self,
        bb_length: int = 20,
        bb_mult: float = 2.0,
        kc_length: int = 20,
        kc_mult: float = 1.5,
        ma_fast: int = 5,
        ma_slow: int = 20,
        stop_atr_mult: float = 2.0,
        atr_length: int = 14,
        max_contracts: int = 1,
        commission_per_contract: float = 5_000,  # 편도 수수료 (원)
        min_squeeze_bars: int = 5,   # 진입 조건: Squeeze 최소 연속 봉 수
        min_momentum: float = 0.3,   # 진입 조건: |momentum| 최솟값
    ):
        self.bb_length      = bb_length
        self.bb_mult        = bb_mult
        self.kc_length      = kc_length
        self.kc_mult        = kc_mult
        self.ma_fast        = ma_fast
        self.ma_slow        = ma_slow
        self.stop_atr_mult  = stop_atr_mult
        self.atr_length     = atr_length
        self.max_contracts  = max_contracts
        self.commission     = commission_per_contract
        self.min_squeeze_bars = min_squeeze_bars
        self.min_momentum     = min_momentum

    def run(self, df: pd.DataFrame) -> BacktestResult:
        """
        O(n) 백테스트: 갭 보정 가격으로 지표 계산, 실제 가격으로 체결.

        Args:
            df: OHLCV DataFrame.
                'date' 컬럼이 있으면 당일 진입/청산(intraday) 강제 적용.
                갭 보정은 자동으로 수행한다.
        """
        from strategy.indicators import (
            bollinger_bands, keltner_channel, squeeze_momentum,
            moving_average, atr as calc_atr,
        )
        from data.gap_adjust import make_indicator_df

        # ---- 갭 보정: 지표는 보정 가격, 체결은 실제 가격 ----
        has_date = "date" in df.columns
        if has_date:
            ind_df = make_indicator_df(df, date_col="date")
            dates  = pd.to_datetime(df["date"]).dt.date.values
        else:
            ind_df = df
            dates  = None

        # ---- 지표 전체 사전 계산 (O(n), 갭 보정 가격 사용) ----
        sq   = squeeze_momentum(ind_df, self.bb_length, self.bb_mult, self.kc_length, self.kc_mult)
        bb   = bollinger_bands(ind_df["close"], self.bb_length, self.bb_mult)
        ma   = moving_average(ind_df["close"], self.ma_fast, self.ma_slow)
        _atr = calc_atr(ind_df["high"], ind_df["low"], ind_df["close"], self.atr_length)

        squeeze_on   = sq["squeeze_on"].values
        momentum     = sq["momentum"].values
        bb_upper     = bb["bb_upper"].values
        bb_lower     = bb["bb_lower"].values
        ma_fast_vals = ma["ma_fast"].values
        ma_slow_vals = ma["ma_slow"].values
        atr_vals     = _atr.values

        # 체결 가격은 원본 사용
        close_vals = df["close"].values
        open_vals  = df["open"].values

        # ---- 연속 Squeeze ON 봉 수 사전 계산 ----
        consecutive_squeeze = np.zeros(len(df), dtype=int)
        for i in range(len(df)):
            if squeeze_on[i]:
                consecutive_squeeze[i] = (consecutive_squeeze[i - 1] + 1) if i > 0 else 1
            else:
                consecutive_squeeze[i] = 0

        result = BacktestResult()
        current_trade: Optional[Trade] = None
        equity = 0.0

        min_idx = max(self.bb_length, self.kc_length, self.ma_slow, self.atr_length) + 3

        for i in range(min_idx, len(df)):
            cur_close = close_vals[i]

            # ---- 당일 진입/청산: 날짜가 바뀌면 전일 종가로 강제 청산 ----
            if has_date and dates is not None and dates[i] != dates[i - 1]:
                if current_trade is not None:
                    eod_price = close_vals[i - 1]
                    current_trade = self._close_trade(
                        current_trade, i - 1, eod_price, "eod", result
                    )
                    equity += current_trade.pnl
                    result.equity_curve.append(equity)
                    current_trade = None

            # ---- 손절 체크 (실제 가격 기준) ----
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
            curr_mom = momentum[i]
            curr_maf = ma_fast_vals[i]
            curr_mas = ma_slow_vals[i]

            if math.isnan(curr_mom) or math.isnan(curr_maf) or math.isnan(curr_mas):
                continue

            signal = None

            if current_trade is not None:
                # 청산: 2봉 연속 모멘텀 반전 or BB 도달
                prev_mom  = momentum[i - 1]
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
                    signal = "exit"
            else:
                # 진입: Squeeze OFF 전환 + 압축 지속 + 모멘텀 강도 + MA 필터
                prev_sq_on  = squeeze_on[i - 1]
                curr_sq_on  = squeeze_on[i]
                squeeze_fired = prev_sq_on and not curr_sq_on
                consec = int(consecutive_squeeze[i - 1])  # prev까지의 연속 squeeze 수

                if squeeze_fired and consec >= self.min_squeeze_bars:
                    if curr_mom > self.min_momentum and curr_maf > curr_mas:
                        signal = "long"
                    elif curr_mom < -self.min_momentum and curr_maf < curr_mas:
                        signal = "short"

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

        # 미결 포지션 강제 청산 (데이터 종료)
        if current_trade is not None:
            current_trade = self._close_trade(
                current_trade, len(df) - 1, close_vals[-1], "end_of_data", result
            )
            equity += current_trade.pnl
            result.equity_curve.append(equity)

        return result

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

        trade.pnl = raw_pnl - self.commission * 2 * qty  # 왕복 수수료
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
    parser.add_argument("--csv", required=True, help="OHLCV CSV 파일 경로")
    parser.add_argument("--bb-length", type=int, default=20)
    parser.add_argument("--bb-mult",   type=float, default=2.0)
    parser.add_argument("--kc-length", type=int, default=20)
    parser.add_argument("--kc-mult",   type=float, default=1.5)
    parser.add_argument("--ma-fast",   type=int, default=5)
    parser.add_argument("--ma-slow",   type=int, default=20)
    parser.add_argument("--stop-atr",  type=float, default=2.0)
    args = parser.parse_args()

    df = pd.read_csv(args.csv)
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float).abs()
    df["volume"] = df["volume"].astype(int).abs()

    engine = BacktestEngine(
        bb_length=args.bb_length,
        bb_mult=args.bb_mult,
        kc_length=args.kc_length,
        kc_mult=args.kc_mult,
        ma_fast=args.ma_fast,
        ma_slow=args.ma_slow,
        stop_atr_mult=args.stop_atr,
    )
    result = engine.run(df)
    result.print_summary()


if __name__ == "__main__":
    main()
