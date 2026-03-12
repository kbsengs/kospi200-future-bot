"""
주문 발송 및 체결 관리.

포지션 상태 (진입가, 수량, 방향) 를 내부적으로 추적한다.
키움 OpenAPI+ 주문 유형:
  1 = 신규매수, 2 = 신규매도, 3 = 매수취소, 4 = 매도취소, 5 = 매수정정, 6 = 매도정정
"""

from dataclasses import dataclass
from typing import Optional

from loguru import logger
from PyQt5.QtCore import QTimer

from kiwoom.api import KiwoomAPI


SCREEN_ORDER   = "6000"
EXIT_MAX_RETRY = 5        # 청산 재시도 최대 횟수
EXIT_RETRY_MS  = 500      # 재시도 간격 (ms)


@dataclass
class Position:
    direction: str       # 'long' or 'short'
    entry_price: float
    qty: int
    stop_price: float = 0.0


class OrderManager:
    def __init__(self, api: KiwoomAPI, config: dict):
        self.api     = api
        self.account = config["kiwoom"]["account"]
        self.code    = config["kiwoom"]["future_code"]
        self.position: Optional[Position] = None
        self._exiting = False          # 청산 주문 진행 중 플래그 (중복 방지)
        self._exit_retry = 0           # 현재 재시도 횟수

    # ------------------------------------------------------------------ #
    # 진입
    # ------------------------------------------------------------------ #
    def enter_long(self, qty: int, stop_price: float) -> bool:
        """시장가 매수 진입 (선물 전용 SendOrderFO)."""
        logger.info(f"[주문] 롱 진입 qty={qty} stop={stop_price}")
        ret = self.api.send_order_fo(
            rq_name="신규매수",
            screen_no=SCREEN_ORDER,
            account=self.account,
            code=self.code,
            ord_kind=1,     # 신규매매
            slby_tp="2",    # 매수
            ord_tp="3",     # 시장가
            qty=qty,
        )
        if ret == 0:
            self.position = Position("long", entry_price=0.0, qty=qty, stop_price=stop_price)
            return True
        logger.error(f"롱 진입 주문 실패: ret={ret}")
        return False

    def enter_short(self, qty: int, stop_price: float) -> bool:
        """시장가 매도 진입 (선물 전용 SendOrderFO)."""
        logger.info(f"[주문] 숏 진입 qty={qty} stop={stop_price}")
        ret = self.api.send_order_fo(
            rq_name="신규매도",
            screen_no=SCREEN_ORDER,
            account=self.account,
            code=self.code,
            ord_kind=1,     # 신규매매
            slby_tp="1",    # 매도
            ord_tp="3",     # 시장가
            qty=qty,
        )
        if ret == 0:
            self.position = Position("short", entry_price=0.0, qty=qty, stop_price=stop_price)
            return True
        logger.error(f"숏 진입 주문 실패: ret={ret}")
        return False

    # ------------------------------------------------------------------ #
    # 청산
    # ------------------------------------------------------------------ #
    def exit_position(self, reason: str = "") -> bool:
        """현재 포지션 전량 시장가 청산.
        - 중복 호출 방지: _exiting 플래그
        - 전송 실패 시 EXIT_MAX_RETRY 회까지 자동 재시도 (QTimer)
        """
        if self.position is None:
            return True
        if self._exiting:
            logger.warning(f"[주문] 청산 중 — 중복 요청 무시 (reason={reason})")
            return True

        self._exiting = True
        self._exit_retry = 0
        self._do_exit(reason)
        return True

    def _do_exit(self, reason: str):
        if self.position is None:
            self._exiting = False
            return

        pos = self.position
        slby_tp = "1" if pos.direction == "long" else "2"
        logger.info(
            f"[주문] 청산 시도 #{self._exit_retry + 1} "
            f"direction={pos.direction} qty={pos.qty} reason={reason}"
        )
        ret = self.api.send_order_fo(
            rq_name="청산",
            screen_no=SCREEN_ORDER,
            account=self.account,
            code=self.code,
            ord_kind=1,
            slby_tp=slby_tp,
            ord_tp="3",     # 시장가 — 반드시 체결
            qty=pos.qty,
        )
        if ret == 0:
            logger.info("[주문] 청산 접수 완료")
            self.position = None
            self._exiting = False
        else:
            self._exit_retry += 1
            if self._exit_retry < EXIT_MAX_RETRY:
                logger.warning(
                    f"[주문] 청산 실패(ret={ret}) — "
                    f"{EXIT_RETRY_MS}ms 후 재시도 ({self._exit_retry}/{EXIT_MAX_RETRY})"
                )
                QTimer.singleShot(EXIT_RETRY_MS, lambda: self._do_exit(reason))
            else:
                logger.critical(
                    f"[주문] 청산 {EXIT_MAX_RETRY}회 실패 — 수동 처리 필요! "
                    f"direction={pos.direction} qty={pos.qty}"
                )
                self._exiting = False

    # ------------------------------------------------------------------ #
    # 체결가 업데이트 (RealtimeHandler 에서 호출)
    # ------------------------------------------------------------------ #
    def update_fill_price(self, fill_price: float):
        if self.position and self.position.entry_price == 0.0:
            self.position.entry_price = fill_price
            logger.info(f"체결가 업데이트: {fill_price}")

    # ------------------------------------------------------------------ #
    # 손절 체크
    # ------------------------------------------------------------------ #
    def check_stop_loss(self, current_price: float) -> bool:
        """손절 조건 충족 시 True 반환 (청산은 호출측에서)."""
        if self.position is None:
            return False
        pos = self.position
        if pos.direction == "long" and current_price <= pos.stop_price:
            logger.warning(f"[손절] 롱 손절 price={current_price} stop={pos.stop_price}")
            return True
        if pos.direction == "short" and current_price >= pos.stop_price:
            logger.warning(f"[손절] 숏 손절 price={current_price} stop={pos.stop_price}")
            return True
        return False

    @property
    def has_position(self) -> bool:
        return self.position is not None

    @property
    def direction(self) -> Optional[str]:
        return self.position.direction if self.position else None
