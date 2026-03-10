"""
키움증권 OpenAPI+ COM 객체 래퍼.
PyQt5 QAxWidget 기반으로 로그인, TR 요청, 주문 발송을 담당한다.

주의: 키움 OpenAPI+는 Windows 환경, 32bit Python 또는 64bit + pywin32 필요.
"""

import time
from typing import Callable, Optional

from PyQt5.QAxContainer import QAxWidget
from PyQt5.QtCore import QEventLoop
from loguru import logger


# TR 요청 간 최소 대기 시간 (API 제한: 1초에 5건)
TR_DELAY = 0.2


class KiwoomAPI(QAxWidget):
    """OpenAPI+ COM 객체를 감싸는 클래스."""

    REAL_SERVER = "KHOPENAPI.KHOpenAPICtrl.1"
    DEMO_SERVER = "KHOPENAPI.KHOpenAPICtrl.1"  # 모의투자도 동일 COM, 서버만 다름

    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.setControl(self.REAL_SERVER)

        self._login_event = QEventLoop()
        self._tr_event = QEventLoop()
        self._tr_data: dict = {}

        # 이벤트 연결
        self.OnEventConnect.connect(self._on_login)
        self.OnReceiveTrData.connect(self._on_tr_data)
        self.OnReceiveMsg.connect(self._on_msg)
        self.OnReceiveChejanData.connect(self._on_chejan)

    # ------------------------------------------------------------------ #
    # 로그인
    # ------------------------------------------------------------------ #
    def login(self) -> bool:
        """로그인 창을 띄우고 완료까지 블로킹."""
        self.dynamicCall("CommConnect()")
        self._login_event.exec_()
        if self.get_login_state() != 1:
            return False
        server_gubun = self.dynamicCall("GetLoginInfo(QString)", "GetServerGubun")
        configured = self.config.get("kiwoom", {}).get("server", "real")
        is_demo = (server_gubun == "1")
        if configured == "demo" and not is_demo:
            logger.warning("설정은 demo이나 실서버에 연결됨 — config.yaml 확인 필요")
        elif configured == "real" and is_demo:
            logger.warning("설정은 real이나 모의투자 서버에 연결됨 — config.yaml 확인 필요")
        return True

    def get_login_state(self) -> int:
        return self.dynamicCall("GetConnectState()")

    def _on_login(self, err_code: int):
        if err_code == 0:
            logger.info("키움 로그인 성공")
        else:
            logger.error(f"키움 로그인 실패: {err_code}")
        self._login_event.exit()

    # ------------------------------------------------------------------ #
    # 계좌 정보
    # ------------------------------------------------------------------ #
    def get_account_list(self) -> list[str]:
        raw = self.dynamicCall("GetLoginInfo(QString)", "ACCNO")
        return [a for a in raw.strip().split(";") if a]

    # ------------------------------------------------------------------ #
    # TR 요청
    # ------------------------------------------------------------------ #
    def set_input_value(self, key: str, value: str):
        self.dynamicCall("SetInputValue(QString, QString)", key, value)

    def comm_rq_data(self, rq_name: str, tr_code: str, prev_next: int, screen: str):
        """TR 요청 후 응답까지 블로킹."""
        ret = self.dynamicCall(
            "CommRqData(QString, QString, int, QString)",
            rq_name, tr_code, prev_next, screen
        )
        if ret == 0:
            self._tr_event.exec_()
        else:
            logger.error(f"TR 요청 실패: {tr_code} ret={ret}")
        time.sleep(TR_DELAY)
        return self._tr_data

    def _on_tr_data(self, screen_no, rq_name, tr_code, record_name, prev_next, *args):
        self._tr_data = {
            "screen_no": screen_no,
            "rq_name": rq_name,
            "tr_code": tr_code,
            "prev_next": prev_next,
        }
        self._tr_event.exit()

    def get_comm_data(self, tr_code: str, record_name: str, index: int, item: str) -> str:
        return self.dynamicCall(
            "GetCommData(QString, QString, int, QString)",
            tr_code, record_name, index, item
        ).strip()

    def get_repeat_cnt(self, tr_code: str, record_name: str) -> int:
        return self.dynamicCall(
            "GetRepeatCnt(QString, QString)", tr_code, record_name
        )

    # ------------------------------------------------------------------ #
    # 주문
    # ------------------------------------------------------------------ #
    def send_order(
        self,
        rq_name: str,
        screen_no: str,
        account: str,
        order_type: int,   # 1=신규매수, 2=신규매도, 3=매수취소, 4=매도취소
        code: str,
        qty: int,
        price: int,
        hoga_gb: str,      # "00"=지정가, "03"=시장가
        org_order_no: str = "",
    ) -> int:
        return self.dynamicCall(
            "SendOrder(QString, QString, QString, int, QString, int, int, QString, QString)",
            [rq_name, screen_no, account, order_type, code, qty, price, hoga_gb, org_order_no]
        )

    def send_order_fo(
        self,
        rq_name: str,
        screen_no: str,
        account: str,
        code: str,
        ord_kind: int,     # 1=신규매매, 2=정정, 3=취소
        slby_tp: str,      # "1"=매도, "2"=매수
        ord_tp: str,       # "1"=지정가, "3"=시장가
        qty: int,
        price: str = "",
        org_ord_no: str = "",
    ) -> int:
        """코스피200 선물/옵션 전용 주문 함수."""
        return self.dynamicCall(
            "SendOrderFO(QString, QString, QString, QString, int, QString, QString, int, QString, QString)",
            [rq_name, screen_no, account, code, ord_kind, slby_tp, ord_tp, qty, price, org_ord_no]
        )

    def get_chejan_data(self, fid: int) -> str:
        """체결/잔고 데이터 조회."""
        return self.dynamicCall("GetChejanData(int)", fid).strip()

    def _on_chejan(self, gubun: str, item_cnt: int, fid_list: str):
        """체결/잔고 이벤트 → RealtimeHandler에서 재정의."""
        pass

    def _on_msg(self, screen_no: str, rq_name: str, tr_code: str, msg: str):
        logger.debug(f"[MSG] {rq_name} {tr_code}: {msg}")

    # ------------------------------------------------------------------ #
    # 실시간 등록
    # ------------------------------------------------------------------ #
    def set_real_reg(self, screen_no: str, codes: str, fids: str, opt_type: str):
        """실시간 데이터 수신 등록."""
        self.dynamicCall(
            "SetRealReg(QString, QString, QString, QString)",
            screen_no, codes, fids, opt_type
        )

    def set_real_remove(self, screen_no: str, code: str):
        self.dynamicCall("SetRealRemove(QString, QString)", screen_no, code)

    def get_comm_real_data(self, code: str, fid: int) -> str:
        return self.dynamicCall(
            "GetCommRealData(QString, int)", code, fid
        ).strip()
