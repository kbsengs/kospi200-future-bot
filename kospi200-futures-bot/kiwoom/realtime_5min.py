"""
실시간 데이터 수신 및 이벤트 처리 — 5분봉 버전.

틱 데이터를 수신하여 5분봉을 집계하고,
매 5분 경계(:00, :05, :10, ..., :55)에 on_bar_close 콜백을 호출한다.
"""

from datetime import datetime
from typing import Callable, Optional

from loguru import logger
from PyQt5.QtCore import QTimer

from .api import KiwoomAPI


# 실시간 FID 상수 (코스피200 선물)
FID_CURRENT_PRICE = 10    # 현재가 (틱 체결가)
FID_CUM_VOLUME    = 13    # 누적거래량 (당일 누적, 절대값)
FID_TICK_VOLUME   = 15    # 틱 거래량 (+매수체결 / -매도체결)
FID_TIME          = 20    # 체결시간 (HHMMSS)

SCREEN_REAL   = "5000"
SCREEN_CHEJAN = "5001"

BAR_MINUTES = 5   # 봉 단위 (분)


class RealtimeHandler5Min:
    """
    실시간 틱 수신 → 5분봉 집계 → 봉 완성 시 on_bar_close 콜백 호출.
    타이머는 매 5분 경계(:00, :05, ..., :55)에 발사된다.
    """

    def __init__(self, api: KiwoomAPI, code: str, on_bar_close: Callable,
                 on_fill: Optional[Callable] = None):
        self.api = api
        self.code = code
        self.on_bar_close = on_bar_close
        self.on_fill = on_fill

        # 현재 집계 중인 5분봉
        self._bar: Optional[dict] = None
        self._bar_start_cumvol: int = 0
        self._last_cumvol: int = 0
        self._bar_delta: int = 0
        self._bar_buy_vol: int = 0
        self._bar_sell_vol: int = 0

        # 체결/잔고 콜백 연결
        self.api.OnReceiveRealData.connect(self._on_real_data)
        self.api.OnReceiveChejanData.connect(self._on_chejan)

        # 실시간 등록
        fids = f"{FID_CURRENT_PRICE};{FID_CUM_VOLUME};{FID_TICK_VOLUME};{FID_TIME}"
        self.api.set_real_reg(SCREEN_REAL, code, fids, "0")
        logger.info(f"실시간 등록 완료 (5분봉): {code}")

        # 다음 5분 경계 타이머 예약
        self._schedule_next_close()

    # ------------------------------------------------------------------ #
    # 5분 경계 타이머
    # ------------------------------------------------------------------ #
    def _schedule_next_close(self):
        """다음 5분 경계(:00/:05/...:55)까지 남은 ms를 계산해 단발 타이머 설정."""
        now = datetime.now()
        minutes_past = now.minute % BAR_MINUTES          # 현재 분이 5분 주기 중 몇 번째인지
        seconds_to_next = (BAR_MINUTES - minutes_past) * 60 - now.second
        ms_remaining = seconds_to_next * 1000 - now.microsecond // 1000

        if ms_remaining <= 0:
            ms_remaining += BAR_MINUTES * 60_000
        elif ms_remaining < 2_000:
            # 경계 직후 재호출 시 중복 발사 방지
            ms_remaining += BAR_MINUTES * 60_000

        QTimer.singleShot(ms_remaining, self._on_bar_close_timer)

    def _on_bar_close_timer(self):
        """5분 경계 도달 — 5분봉 완성 후 다음 타이머 예약."""
        now_str = datetime.now().strftime("%H:%M:%S")
        if self._bar is not None:
            vol = max(0, self._last_cumvol - self._bar_start_cumvol)
            self._bar["volume"]   = vol
            self._bar["cumvol"]   = self._last_cumvol
            self._bar["delta"]    = self._bar_delta
            self._bar["buy_vol"]  = self._bar_buy_vol
            self._bar["sell_vol"] = self._bar_sell_vol
            dom = "매수우위" if self._bar_delta > 0 else ("매도우위" if self._bar_delta < 0 else "중립")
            logger.info(
                f"[5분봉완성] {now_str} "
                f"close={self._bar['close']} vol={vol} "
                f"buy={self._bar_buy_vol} sell={self._bar_sell_vol} "
                f"delta={self._bar_delta:+d} ({dom})"
            )
            self.on_bar_close(self._bar.copy())
        else:
            logger.info(f"[타이머] {now_str} 틱 미수신 — 실시간 데이터 확인 필요")

        self._bar = None
        self._bar_start_cumvol = self._last_cumvol
        self._bar_delta    = 0
        self._bar_buy_vol  = 0
        self._bar_sell_vol = 0
        self._schedule_next_close()

    # ------------------------------------------------------------------ #
    # 실시간 틱 수신
    # ------------------------------------------------------------------ #
    def _on_real_data(self, code: str, real_type: str, real_data: str):
        if code != self.code:
            return
        if real_type not in ("주식체결", "선물시세", "선물체결"):
            return

        raw_price   = self.api.get_comm_real_data(real_type, FID_CURRENT_PRICE)
        raw_cumvol  = self.api.get_comm_real_data(real_type, FID_CUM_VOLUME)
        raw_tickvol = self.api.get_comm_real_data(real_type, FID_TICK_VOLUME)
        raw_time    = self.api.get_comm_real_data(real_type, FID_TIME)

        if not raw_time or not raw_price:
            return

        try:
            price    = abs(float(raw_price))
            cumvol   = abs(int(raw_cumvol)) if raw_cumvol else 0
            tick_vol = int(raw_tickvol) if raw_tickvol else 0
        except ValueError:
            return

        self._last_cumvol  = cumvol
        self._bar_delta   += tick_vol
        if tick_vol > 0:
            self._bar_buy_vol  += tick_vol
        elif tick_vol < 0:
            self._bar_sell_vol += abs(tick_vol)

        if self._bar is None:
            self._start_bar(raw_time, price, cumvol)
        else:
            self._update_bar(price, cumvol)

    def _start_bar(self, raw_time: str, price: float, cumvol: int):
        """새 5분봉 시작. raw_time = HHMMSS."""
        now = datetime.now()
        # 5분 경계에 맞춘 시작 시각 계산 (예: 09:13 → 09:10)
        minute_aligned = (now.minute // BAR_MINUTES) * BAR_MINUTES
        bar_hhmm = now.strftime("%H") + f"{minute_aligned:02d}"
        self._bar_start_cumvol = cumvol
        self._bar = {
            "date":   now.strftime("%Y/%m/%d"),
            "time":   now.strftime("%Y%m%d") + bar_hhmm + "00",
            "open":   price,
            "high":   price,
            "low":    price,
            "close":  price,
            "volume": 0,
            "cumvol": cumvol,
            "delta":  0,
        }

    def _update_bar(self, price: float, cumvol: int):
        if self._bar is None:
            return
        self._bar["high"]   = max(self._bar["high"], price)
        self._bar["low"]    = min(self._bar["low"],  price)
        self._bar["close"]  = price
        self._bar["cumvol"] = cumvol

    # ------------------------------------------------------------------ #
    # 체결/잔고 이벤트
    # ------------------------------------------------------------------ #
    def _on_chejan(self, gubun: str, item_cnt: int, fid_list: str):
        if gubun == "0":
            order_no   = self.api.dynamicCall("GetChejanData(int)", 9203).strip()
            order_stat = self.api.dynamicCall("GetChejanData(int)", 913).strip()
            qty        = self.api.dynamicCall("GetChejanData(int)", 911).strip()
            price      = self.api.dynamicCall("GetChejanData(int)", 910).strip()
            logger.info(f"[체결] 주문번호={order_no} 상태={order_stat} qty={qty} price={price}")
            if self.on_fill and price:
                try:
                    self.on_fill(abs(float(price)))
                except ValueError:
                    pass

    def unregister(self):
        self.api.set_real_remove(SCREEN_REAL, self.code)
        logger.info(f"실시간 해제: {self.code}")
