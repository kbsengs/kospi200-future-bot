"""
코스피200 선물 자동매매 봇 - 진입점.

실행:
    python main.py                    # 실거래/모의투자 모드
    python -m backtest.engine --csv sample.csv  # 백테스트 모드

장 운영시간: 08:45 ~ 15:45 (코스피200 선물 기준)
신규 진입 금지: 15:30 이후
"""

import sys
import yaml
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Optional

import pandas as pd
from loguru import logger
from PyQt5.QtWidgets import QApplication

from kiwoom.api import KiwoomAPI
from kiwoom.realtime import RealtimeHandler
from data.history import HistoryManager
from data.gap_adjust import make_indicator_df
from strategy.signal import generate_signal
from trading.order_manager import OrderManager
from trading.risk_manager import RiskManager


# ------------------------------------------------------------------ #
# 설정 로딩
# ------------------------------------------------------------------ #
def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ------------------------------------------------------------------ #
# 로거 설정
# ------------------------------------------------------------------ #
def setup_logger(config: dict):
    log_cfg = config.get("logging", {})
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}",
        level=log_cfg.get("level", "INFO"),
    )
    logger.add(
        log_cfg.get("file", "logs/trade.log"),
        rotation=log_cfg.get("rotation", "1 day"),
        retention=log_cfg.get("retention", "30 days"),
        encoding="utf-8",
        level="DEBUG",
    )


# ------------------------------------------------------------------ #
# 메인 봇 클래스
# ------------------------------------------------------------------ #
POINT_VALUE = 250_000   # 코스피200 선물 1포인트 = 250,000원
COMMISSION  = 5_000    # 편도 수수료 (원)


class TradingBot:
    def __init__(self, config: dict, api: KiwoomAPI):
        self.config  = config
        self.api     = api
        self.code    = config["kiwoom"]["future_code"]
        self.account = config["kiwoom"]["account"]

        hours_cfg = config["trading_hours"]
        self.market_open      = dtime(*map(int, hours_cfg["start"].split(":")))
        self.market_close     = dtime(*map(int, hours_cfg["end"].split(":")))
        self.no_entry_after   = dtime(*map(int, hours_cfg["no_entry_after"].split(":")))

        strat = config["strategy"]
        self.bb_length       = strat["squeeze"]["bb_length"]
        self.bb_mult         = strat["squeeze"]["bb_mult"]
        self.kc_length       = strat["squeeze"]["kc_length"]
        self.kc_mult         = strat["squeeze"]["kc_mult"]
        self.ma_fast         = strat["ma"]["fast"]
        self.ma_slow         = strat["ma"]["slow"]
        self.min_squeeze_bars = strat["squeeze"].get("min_squeeze_bars", 5)
        self.min_momentum     = strat["squeeze"].get("min_momentum", 0.3)

        self.history  = HistoryManager(api, self.code, strat["timeframe"])
        self.order_mgr = OrderManager(api, config)
        self.risk_mgr  = RiskManager(config)
        self.realtime: Optional[RealtimeHandler] = None

        self._df: pd.DataFrame = pd.DataFrame()

    # ------------------------------------------------------------------ #
    # 시작
    # ------------------------------------------------------------------ #
    def start(self):
        logger.info("봇 시작: 과거 데이터 로딩")
        self._df = self.history.load_initial(count=150)

        self.risk_mgr.reset_daily()

        logger.info("실시간 수신 등록")
        self.realtime = RealtimeHandler(
            api=self.api,
            code=self.code,
            on_bar_close=self._on_bar_close,
            on_fill=self.order_mgr.update_fill_price,
        )
        logger.info(f"자동매매 대기 중 ({self.code}) | 장: {self.market_open}~{self.market_close}")

    # ------------------------------------------------------------------ #
    # 분봉 완성 콜백
    # ------------------------------------------------------------------ #
    def _on_bar_close(self, bar: dict):
        now = datetime.now().time()

        # 장외 시간 → 무시
        if not (self.market_open <= now <= self.market_close):
            return

        # 실시간 봉 추가
        self.history.append_bar(bar)
        self._df = self.history.to_dataframe()

        # 손절 틱 단위 체크 (봉 종가 기준)
        current_price = bar["close"]
        if self.order_mgr.has_position:
            if self.order_mgr.check_stop_loss(current_price):
                self._record_pnl(self.order_mgr.position.stop_price)
                self.order_mgr.exit_position(reason="stop_loss")
                return

        # 일일 한도 초과 또는 장 마감 직전
        if self.risk_mgr.is_trading_halted:
            return

        # 장 마감 강제 청산
        if now >= self.market_close:
            if self.order_mgr.has_position:
                logger.info("장 마감 강제 청산")
                self._record_pnl(current_price)
                self.order_mgr.exit_position(reason="market_close")
            return

        # 신호 생성 (갭 보정된 df로 지표 계산)
        ind_df = make_indicator_df(self._df, date_col="date")
        signal = generate_signal(
            df=ind_df,
            current_position=self.order_mgr.direction,
            bb_length=self.bb_length,
            bb_mult=self.bb_mult,
            kc_length=self.kc_length,
            kc_mult=self.kc_mult,
            ma_fast=self.ma_fast,
            ma_slow=self.ma_slow,
            min_squeeze_bars=self.min_squeeze_bars,
            min_momentum=self.min_momentum,
        )

        logger.debug(f"신호: {signal} | 포지션: {self.order_mgr.direction}")

        if signal == "exit":
            self._record_pnl(current_price)
            self.order_mgr.exit_position(reason="signal")

        elif signal in ("long", "short") and not self.order_mgr.has_position:
            # 신규 진입 시간 제한 (15:30 이후 진입 금지)
            if now >= self.no_entry_after:
                logger.info(f"신규 진입 금지 시각 이후 ({self.no_entry_after}) → 신호 무시")
                return

            qty = self.risk_mgr.get_order_qty(
                balance=0,           # 실거래 시 잔고 조회 필요
                current_price=current_price,
            )
            stop = self.risk_mgr.calc_stop_price(self._df, signal, current_price)

            if signal == "long":
                self.order_mgr.enter_long(qty, stop)
            else:
                self.order_mgr.enter_short(qty, stop)

    def _record_pnl(self, exit_price: float):
        """포지션 청산 직전 PnL을 계산해 리스크 매니저에 기록."""
        pos = self.order_mgr.position
        if pos is None or pos.entry_price <= 0:
            return
        qty = pos.qty
        if pos.direction == "long":
            raw_pnl = (exit_price - pos.entry_price) * POINT_VALUE * qty
        else:
            raw_pnl = (pos.entry_price - exit_price) * POINT_VALUE * qty
        pnl = raw_pnl - COMMISSION * 2 * qty   # 왕복 수수료
        self.risk_mgr.record_trade_pnl(pnl)

    def stop(self):
        if self.order_mgr.has_position:
            logger.info("봇 종료 - 포지션 청산")
            self.order_mgr.exit_position(reason="bot_stop")
        if self.realtime:
            self.realtime.unregister()
        logger.info("봇 종료 완료")


# ------------------------------------------------------------------ #
# 진입점
# ------------------------------------------------------------------ #
def main():
    config = load_config("config.yaml")
    setup_logger(config)

    app = QApplication(sys.argv)
    api = KiwoomAPI(config)

    logger.info("키움증권 OpenAPI+ 로그인 시도...")
    if not api.login():
        logger.error("로그인 실패. 종료합니다.")
        sys.exit(1)

    accounts = api.get_account_list()
    logger.info(f"보유 계좌: {accounts}")

    bot = TradingBot(config, api)
    bot.start()

    try:
        sys.exit(app.exec_())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt 수신")
    finally:
        bot.stop()


if __name__ == "__main__":
    main()
