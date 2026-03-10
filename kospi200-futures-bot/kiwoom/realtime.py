"""
실시간 데이터 수신 및 이벤트 처리.
분봉 완성을 감지하여 전략 콜백을 트리거한다.
"""

from datetime import datetime, date as ddate, time as dtime
from typing import Callable, Optional

from loguru import logger

from .api import KiwoomAPI


# 실시간 FID 상수 (코스피200 선물)
FID_CURRENT_PRICE = 10    # 현재가
FID_VOLUME        = 15    # 거래량
FID_TIME          = 20    # 체결시간 (HHMMSS)
FID_OPEN          = 16    # 시가
FID_HIGH          = 17    # 고가
FID_LOW           = 18    # 저가

SCREEN_REAL = "5000"
SCREEN_CHEJAN = "5001"


class RealtimeHandler:
    """
    실시간 틱 수신 → 분봉 집계 → 봉 완성 시 on_bar_close 콜백 호출.
    """

    def __init__(self, api: KiwoomAPI, code: str, on_bar_close: Callable,
                 on_fill: Optional[Callable] = None):
        self.api = api
        self.code = code
        self.on_bar_close = on_bar_close   # 완성된 분봉 dict 전달
        self.on_fill = on_fill             # 체결가 콜백 (OrderManager.update_fill_price)

        # 현재 집계 중인 분봉
        self._bar: Optional[dict] = None
        self._current_minute: Optional[str] = None

        # 체결/잔고 콜백 재정의
        self.api.OnReceiveRealData.connect(self._on_real_data)
        self.api.OnReceiveChejanData.connect(self._on_chejan)

        # 실시간 등록 (FID 목록: 현재가, 거래량, 체결시간, 시/고/저)
        fids = f"{FID_CURRENT_PRICE};{FID_VOLUME};{FID_TIME};{FID_OPEN};{FID_HIGH};{FID_LOW}"
        self.api.set_real_reg(SCREEN_REAL, code, fids, "0")
        logger.info(f"실시간 등록 완료: {code}")

    # ------------------------------------------------------------------ #
    # 실시간 틱 수신
    # ------------------------------------------------------------------ #
    def _on_real_data(self, code: str, real_type: str, real_data: str):
        if code != self.code:
            return
        if real_type not in ("주식체결", "선물시세", "선물체결"):
            return

        raw_time = self.api.get_comm_real_data(code, FID_TIME)       # HHMMSS
        raw_price = self.api.get_comm_real_data(code, FID_CURRENT_PRICE)
        raw_vol   = self.api.get_comm_real_data(code, FID_VOLUME)

        if not raw_time or not raw_price:
            return

        try:
            price = abs(int(raw_price))
            volume = abs(int(raw_vol))
        except ValueError:
            return

        minute = raw_time[:4]   # HHMM — 분봉 단위 식별자

        if self._current_minute is None:
            self._start_bar(minute, price, volume)
        elif minute != self._current_minute:
            self._close_bar()
            self._start_bar(minute, price, volume)
        else:
            self._update_bar(price, volume)

    def _start_bar(self, minute: str, price: int, volume: int):
        self._current_minute = minute
        self._bar = {
            "date":   datetime.now().strftime("%Y/%m/%d"),
            "time":   minute,
            "open":   price,
            "high":   price,
            "low":    price,
            "close":  price,
            "volume": volume,
        }

    def _update_bar(self, price: int, volume: int):
        if self._bar is None:
            return
        self._bar["high"]   = max(self._bar["high"], price)
        self._bar["low"]    = min(self._bar["low"],  price)
        self._bar["close"]  = price
        self._bar["volume"] += volume

    def _close_bar(self):
        if self._bar:
            logger.debug(f"분봉 완성: {self._bar}")
            self.on_bar_close(self._bar.copy())

    # ------------------------------------------------------------------ #
    # 체결/잔고 이벤트
    # ------------------------------------------------------------------ #
    def _on_chejan(self, gubun: str, item_cnt: int, fid_list: str):
        """
        gubun: "0" = 주문체결, "1" = 잔고
        """
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
