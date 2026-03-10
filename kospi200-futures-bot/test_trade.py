"""
테스트 주문: 숏 진입 → 10초 후 청산
체결 이벤트(OnReceiveChejan)로 진입가/청산가/손익을 확인한다.
"""

import sys
import yaml
from loguru import logger
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer

from kiwoom.api import KiwoomAPI

POINT_VALUE = 250_000   # 1포인트 = 250,000원
COMMISSION  = 5_000     # 편도 수수료


def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class TestTrader:
    def __init__(self, api: KiwoomAPI, config: dict):
        self.api     = api
        self.account = config["kiwoom"]["account"]
        self.code    = config["kiwoom"]["future_code"]
        self.entry_price = 0.0
        self.exit_price  = 0.0
        self._phase = "idle"   # idle → entered → exited

        # 체결 이벤트 콜백 연결
        self.api.OnReceiveChejanData.connect(self._on_chejan)

    # ------------------------------------------------------------------ #
    # 체결 이벤트
    # ------------------------------------------------------------------ #
    def _on_chejan(self, gubun: str, item_cnt: int, fid_list: str):
        """
        gubun "0" : 주문접수/체결
        gubun "1" : 잔고 변경
        """
        if gubun != "0":
            return

        order_status = self.api.get_chejan_data(913)   # 주문상태: 체결
        fill_price_str = self.api.get_chejan_data(910)  # 체결가
        fill_qty_str   = self.api.get_chejan_data(911)  # 체결량
        unfilled_str   = self.api.get_chejan_data(902)  # 미체결수량
        order_no       = self.api.get_chejan_data(9203) # 주문번호
        slby           = self.api.get_chejan_data(907)  # 매도수구분 (1:매도, 2:매수)

        logger.info(
            f"[체결] 상태={order_status} 주문번호={order_no} "
            f"매도수={slby} 체결가={fill_price_str} 체결량={fill_qty_str} 미체결={unfilled_str}"
        )

        # 체결가 파싱
        try:
            fill_price = abs(float(fill_price_str.replace(",", "")))
            fill_qty   = int(fill_qty_str) if fill_qty_str else 0
        except (ValueError, AttributeError):
            return

        if fill_qty == 0 or fill_price == 0:
            return

        # 진입 체결 (숏 = 매도, slby=1)
        if self._phase == "entered" and slby == "1" and self.entry_price == 0.0:
            self.entry_price = fill_price
            logger.info(f"▶ 진입 체결가: {fill_price:,.2f}")

        # 청산 체결 (매수, slby=2)
        elif self._phase == "exited" and slby == "2" and self.exit_price == 0.0:
            self.exit_price = fill_price
            logger.info(f"▶ 청산 체결가: {fill_price:,.2f}")
            self._print_result()

    # ------------------------------------------------------------------ #
    # 주문 흐름
    # ------------------------------------------------------------------ #
    def run(self):
        logger.info("=== 테스트 주문 시작 ===")
        logger.info(f"계좌: {self.account} / 종목: {self.code}")

        logger.info("[1] 숏 진입 주문 (시장가 매도 1계약)")
        ret = self.api.send_order_fo(
            rq_name="테스트숏진입",
            screen_no="9001",
            account=self.account,
            code=self.code,
            ord_kind=1,
            slby_tp="1",    # 매도
            ord_tp="3",     # 시장가
            qty=1,
        )
        logger.info(f"진입 주문 접수: {'성공(0)' if ret == 0 else f'실패({ret})'}")

        if ret != 0:
            logger.error("진입 주문 실패 — 종료")
            QApplication.quit()
            return

        self._phase = "entered"
        logger.info("[2] 10초 대기 중...")
        QTimer.singleShot(10_000, self._exit)

    def _exit(self):
        logger.info("[3] 청산 주문 (시장가 매수 1계약)")
        ret = self.api.send_order_fo(
            rq_name="테스트숏청산",
            screen_no="9001",
            account=self.account,
            code=self.code,
            ord_kind=1,
            slby_tp="2",    # 매수 (숏 청산)
            ord_tp="3",     # 시장가
            qty=1,
        )
        logger.info(f"청산 주문 접수: {'성공(0)' if ret == 0 else f'실패({ret})'}")
        self._phase = "exited"

        # 체결 이벤트 대기 후 종료
        QTimer.singleShot(5_000, self._finalize)

    def _print_result(self):
        if self.entry_price > 0 and self.exit_price > 0:
            raw_pnl = (self.entry_price - self.exit_price) * POINT_VALUE  # 숏: 진입 - 청산
            net_pnl = raw_pnl - COMMISSION * 2  # 왕복 수수료
            logger.info("=" * 50)
            logger.info(f"  진입가  : {self.entry_price:>10,.2f}")
            logger.info(f"  청산가  : {self.exit_price:>10,.2f}")
            logger.info(f"  원손익  : {raw_pnl:>10,.0f} 원")
            logger.info(f"  수수료  : {COMMISSION*2:>10,.0f} 원 (왕복)")
            logger.info(f"  순손익  : {net_pnl:>10,.0f} 원")
            logger.info("=" * 50)

    def _finalize(self):
        if self.entry_price == 0 or self.exit_price == 0:
            logger.warning("체결가 미수신 — HTS에서 직접 확인 필요")
            logger.info(f"  진입가 수신: {self.entry_price}")
            logger.info(f"  청산가 수신: {self.exit_price}")
        logger.info("=== 테스트 종료 ===")
        QApplication.quit()


def main():
    config = load_config()
    app = QApplication(sys.argv)
    api = KiwoomAPI(config)

    logger.info("로그인 시도...")
    if not api.login():
        logger.error("로그인 실패")
        sys.exit(1)

    # 계좌 비밀번호 입력창 표시 (등록 후 자동 사용)
    api.dynamicCall("KOA_Functions(QString, QString)", ["ShowAccountWindow", ""])
    logger.info("계좌 비밀번호 입력창이 열립니다. 비밀번호 입력 후 [등록] 클릭하세요.")

    trader = TestTrader(api, config)
    # 비밀번호 등록 대기 후 주문 (5초)
    QTimer.singleShot(5_000, trader.run)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
