"""
키움 OpenAPI+ 모의투자 연결 테스트.

실행 전 체크리스트:
  1. 키움 OpenAPI+ 설치 완료 (https://www1.kiwoom.com/nkw.templateFrameSet.do?m=m1408000000)
  2. 모의투자 신청 완료 (HTS → 모의투자 신청)
  3. 이 스크립트를 32bit Python으로 실행

실행:
    python test_connection.py

테스트 항목:
  1. COM 객체 초기화
  2. 로그인 (팝업 창 → ID/PW 입력)
  3. 계좌 목록 조회
  4. 코스피200 선물 현재가 TR 조회 (opt50001)
  5. 분봉 데이터 조회 (opt50028)
"""

import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QAxContainer import QAxWidget
from PyQt5.QtCore import QEventLoop
from loguru import logger

logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")


class ConnectionTest(QAxWidget):
    FUTURE_CODE = "101N9000"   # 코스피200 근월물 (매월 갱신 필요)
    SCREEN = "9000"

    def __init__(self):
        super().__init__()
        self._login_loop = QEventLoop()
        self._tr_loop    = QEventLoop()
        self._tr_result  = {}
        self.passed = []
        self.failed = []

    def run_all_tests(self):
        logger.info("=" * 50)
        logger.info("  키움 OpenAPI+ 연결 테스트 시작")
        logger.info("=" * 50)

        # 1. COM 초기화
        self._test_com_init()
        if "COM 초기화" in self.failed:
            self._print_result()
            return

        # 2. 로그인
        self._test_login()
        if "로그인" in self.failed:
            self._print_result()
            return

        # 3. 계좌 조회
        self._test_account()

        # 4. 현재가 TR
        self._test_current_price()

        # 5. 분봉 TR
        self._test_minute_bars()

        self._print_result()

    # ------------------------------------------------------------------ #
    # 1. COM 초기화
    # ------------------------------------------------------------------ #
    def _test_com_init(self):
        name = "COM 초기화"
        try:
            self.setControl("OpenAPI.KHOpenAPI.1")
            self.OnEventConnect.connect(self._on_login)
            self.OnReceiveTrData.connect(self._on_tr_data)
            logger.info(f"[PASS] {name}")
            self.passed.append(name)
        except Exception as e:
            logger.error(f"[FAIL] {name}: {e}")
            logger.error("  → 키움 OpenAPI+가 설치되어 있는지 확인하세요.")
            logger.error("  → 다운로드: https://www1.kiwoom.com")
            self.failed.append(name)

    # ------------------------------------------------------------------ #
    # 2. 로그인
    # ------------------------------------------------------------------ #
    def _test_login(self):
        name = "로그인"
        logger.info("로그인 팝업이 열립니다. 모의투자 ID/PW를 입력하세요...")
        try:
            self.dynamicCall("CommConnect()")
            self._login_loop.exec_()

            state = self.dynamicCall("GetConnectState()")
            if state == 1:
                server = self.dynamicCall("GetLoginInfo(QString)", "GetServerGubun")
                server_name = "모의투자" if server == "1" else "실서버"
                logger.info(f"[PASS] {name} (서버: {server_name})")
                if server != "1":
                    logger.warning("  → 실서버에 연결됨! config.yaml server를 확인하세요.")
                self.passed.append(name)
            else:
                logger.error(f"[FAIL] {name}: 연결 상태 = {state}")
                self.failed.append(name)
        except Exception as e:
            logger.error(f"[FAIL] {name}: {e}")
            self.failed.append(name)

    def _on_login(self, err_code: int):
        if err_code == 0:
            logger.info("로그인 이벤트 수신: 성공")
        else:
            logger.error(f"로그인 이벤트 수신: 실패 (err={err_code})")
        self._login_loop.exit()

    # ------------------------------------------------------------------ #
    # 3. 계좌 목록
    # ------------------------------------------------------------------ #
    def _test_account(self):
        name = "계좌 조회"
        try:
            raw = self.dynamicCall("GetLoginInfo(QString)", "ACCNO")
            accounts = [a for a in raw.strip().split(";") if a]
            if accounts:
                logger.info(f"[PASS] {name}: {accounts}")
                self.passed.append(name)
            else:
                logger.warning(f"[WARN] {name}: 계좌 없음")
                self.failed.append(name)
        except Exception as e:
            logger.error(f"[FAIL] {name}: {e}")
            self.failed.append(name)

    # ------------------------------------------------------------------ #
    # 4. 현재가 TR (opt50001)
    # ------------------------------------------------------------------ #
    def _test_current_price(self):
        name = "현재가 TR"
        import time
        try:
            self.dynamicCall("SetInputValue(QString, QString)", "종목코드", self.FUTURE_CODE)
            ret = self.dynamicCall("CommRqData(QString,QString,int,QString)",
                                   "현재가조회", "opt50001", 0, self.SCREEN)
            if ret != 0:
                logger.error(f"[FAIL] {name}: CommRqData 반환값={ret}")
                self.failed.append(name)
                return
            self._tr_loop.exec_()
            time.sleep(0.2)

            price = self.dynamicCall("GetCommData(QString,QString,int,QString)",
                                     "opt50001", "opt50001", 0, "현재가").strip()
            if price:
                logger.info(f"[PASS] {name}: 현재가={abs(int(price)):,}")
                self.passed.append(name)
            else:
                logger.warning(f"[WARN] {name}: 데이터 없음 (장 외 시간일 수 있음)")
                self.passed.append(name + " (장외)")
        except Exception as e:
            logger.error(f"[FAIL] {name}: {e}")
            self.failed.append(name)

    # ------------------------------------------------------------------ #
    # 5. 분봉 TR (opt50028)
    # ------------------------------------------------------------------ #
    def _test_minute_bars(self):
        name = "분봉 TR"
        import time
        try:
            self.dynamicCall("SetInputValue(QString, QString)", "종목코드", self.FUTURE_CODE)
            self.dynamicCall("SetInputValue(QString, QString)", "틱범위", "1")
            self.dynamicCall("SetInputValue(QString, QString)", "수정주가구분", "1")
            ret = self.dynamicCall("CommRqData(QString,QString,int,QString)",
                                   "분봉조회", "opt50028", 0, self.SCREEN)
            if ret != 0:
                logger.error(f"[FAIL] {name}: CommRqData 반환값={ret}")
                self.failed.append(name)
                return
            self._tr_loop.exec_()
            time.sleep(0.2)

            cnt = self.dynamicCall("GetRepeatCnt(QString,QString)", "opt50028", "opt50028")
            if cnt > 0:
                t   = self.dynamicCall("GetCommData(QString,QString,int,QString)",
                                       "opt50028", "opt50028", 0, "체결시간").strip()
                c   = self.dynamicCall("GetCommData(QString,QString,int,QString)",
                                       "opt50028", "opt50028", 0, "현재가").strip()
                logger.info(f"[PASS] {name}: {cnt}개 봉 수신 | 최신봉 시간={t} 종가={abs(float(c)):.2f}")
                self.passed.append(name)
            else:
                logger.warning(f"[WARN] {name}: 데이터 0건 (장 외 시간 또는 종목코드 확인)")
                self.passed.append(name + " (0건)")
        except Exception as e:
            logger.error(f"[FAIL] {name}: {e}")
            self.failed.append(name)

    def _on_tr_data(self, *args):
        self._tr_loop.exit()

    # ------------------------------------------------------------------ #
    # 결과 출력
    # ------------------------------------------------------------------ #
    def _print_result(self):
        logger.info("")
        logger.info("=" * 50)
        logger.info(f"  통과: {len(self.passed)}개  |  실패: {len(self.failed)}개")
        for p in self.passed:
            logger.info(f"  ✓ {p}")
        for f in self.failed:
            logger.error(f"  ✗ {f}")
        logger.info("=" * 50)

        if not self.failed:
            logger.info("모든 테스트 통과! main.py 실행 가능합니다.")
        else:
            logger.error("일부 테스트 실패. 위 오류 메시지를 확인하세요.")


def main():
    app = QApplication(sys.argv)
    tester = ConnectionTest()
    tester.run_all_tests()
    app.quit()


if __name__ == "__main__":
    main()
