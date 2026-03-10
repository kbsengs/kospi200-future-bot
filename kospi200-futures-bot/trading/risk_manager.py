"""
리스크 관리 모듈.

- 계좌 잔고 대비 최대 계약수 결정
- ATR 기반 손절가 계산
- 일일 최대 손실 한도 관리
"""

import pandas as pd
from loguru import logger

from strategy.indicators import atr


class RiskManager:
    def __init__(self, config: dict):
        self.max_contracts   = config["risk"]["max_contracts"]
        self.stop_atr_mult   = config["risk"]["stop_atr_mult"]
        self.max_daily_loss  = config["risk"]["max_daily_loss"]
        self._daily_pnl: float = 0.0
        self._trading_halted: bool = False

    # ------------------------------------------------------------------ #
    # 손절가 계산
    # ------------------------------------------------------------------ #
    def calc_stop_price(
        self,
        df: pd.DataFrame,
        direction: str,
        entry_price: float,
        atr_length: int = 14,
    ) -> float:
        """
        ATR × stop_atr_mult 로 손절가 산출.

        Args:
            df       : OHLCV DataFrame
            direction: 'long' or 'short'
            entry_price: 체결가
        """
        _atr = atr(df["high"], df["low"], df["close"], atr_length)
        atr_val = _atr.iloc[-1]

        if pd.isna(atr_val) or atr_val == 0:
            # ATR 계산 불가 시 0.5% 고정 손절
            fallback = entry_price * 0.005
            atr_val = fallback
            logger.warning(f"ATR 계산 불가, 고정 손절 사용: {atr_val:.2f}")

        stop_distance = atr_val * self.stop_atr_mult

        if direction == "long":
            stop = entry_price - stop_distance
        else:
            stop = entry_price + stop_distance

        logger.info(f"손절가 계산: direction={direction} entry={entry_price:.2f} "
                    f"ATR={atr_val:.2f} stop={stop:.2f}")
        return round(stop, 2)

    # ------------------------------------------------------------------ #
    # 계약수 결정
    # ------------------------------------------------------------------ #
    def get_order_qty(self, balance: float, current_price: float) -> int:
        """
        계좌 잔고와 설정 최대값 중 안전한 계약수 반환.
        코스피200 선물 1계약 = 종목가격 × 250,000원 (증거금 ~10%)

        현재는 단순히 max_contracts 반환 (실거래 시 증거금 로직 추가 권장).
        """
        return self.max_contracts

    # ------------------------------------------------------------------ #
    # 일일 손익 관리
    # ------------------------------------------------------------------ #
    def record_trade_pnl(self, pnl: float):
        """체결 완료 후 손익 기록."""
        self._daily_pnl += pnl
        logger.info(f"누적 일일 손익: {self._daily_pnl:,.0f}원")

        if self._daily_pnl <= -self.max_daily_loss:
            self._trading_halted = True
            logger.warning(
                f"일일 최대 손실 한도 도달 ({self.max_daily_loss:,}원), 거래 중단"
            )

    def reset_daily(self):
        """장 시작 시 일일 손익 초기화."""
        self._daily_pnl = 0.0
        self._trading_halted = False
        logger.info("일일 손익 초기화")

    @property
    def is_trading_halted(self) -> bool:
        return self._trading_halted

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl
