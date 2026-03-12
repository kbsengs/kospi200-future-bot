"""
과거 OHLCV 데이터 로딩 및 관리.

키움 opt50029 (선물분봉차트조회) TR을 사용하여
초기 히스토리를 로딩하고, 실시간 봉 완성 시 롤링 업데이트한다.
"""

from collections import deque
from datetime import datetime
from typing import Optional

import pandas as pd
from loguru import logger

from kiwoom.api import KiwoomAPI


# 최대 보관 봉 수 — 전날 전체(~405) + 당일 전체(~405) + 여유분
MAX_BARS = 900


class HistoryManager:
    """
    분봉 OHLCV 데이터를 관리하는 클래스.
    초기 로딩: 키움 TR → 실시간 봉 추가: append_bar()
    """

    def __init__(self, api: KiwoomAPI, code: str, timeframe: str = "1"):
        self.api       = api
        self.code      = code
        self.timeframe = timeframe
        self._bars: deque[dict] = deque(maxlen=MAX_BARS)

    # ------------------------------------------------------------------ #
    # 초기 데이터 로딩 (키움 TR)
    # ------------------------------------------------------------------ #
    def load_initial(self, count: int = 100) -> pd.DataFrame:
        """
        opt50029 (선물분봉차트조회) TR로 과거 분봉 데이터 로딩.

        키움 TR 필드:
          입력: 종목코드, 시간단위 (1=1분, 3=3분, ...)
          출력: 체결시간(YYYYMMDDHHmmss), 시가, 고가, 저가, 현재가(종가), 거래량
          ※ record_name = "" (빈 문자열), 페이지당 최대 900봉
          ※ prev_next=="2" 이면 연속조회 필요
        """
        logger.info(f"과거 데이터 로딩 시작: {self.code} {self.timeframe}분봉 {count}개")

        rows: list = []
        prev_next = 0

        while len(rows) < count:
            page_rows: list = []
            remaining = count - len(rows)

            def _read_page(api, _page=page_rows, _remaining=remaining):
                """OnReceiveTrData 콜백 내부에서 호출 — GetRepeatCnt/GetCommData 유효 시점."""
                rec = ""  # opt50029의 record_name은 빈 문자열
                cnt = api.get_repeat_cnt("opt50029", rec)
                logger.info(f"[TR콜백] get_repeat_cnt={cnt} remaining={_remaining}")
                need = min(cnt, _remaining)
                for i in range(need):
                    t   = api.get_comm_data("opt50029", rec, i, "체결시간").strip()
                    op  = self._to_float(api.get_comm_data("opt50029", rec, i, "시가"))
                    hi  = self._to_float(api.get_comm_data("opt50029", rec, i, "고가"))
                    lo  = self._to_float(api.get_comm_data("opt50029", rec, i, "저가"))
                    cl  = self._to_float(api.get_comm_data("opt50029", rec, i, "현재가"))
                    vol = self._to_int(api.get_comm_data("opt50029", rec, i, "거래량"))
                    date_str = f"{t[:4]}/{t[4:6]}/{t[6:8]}" if len(t) >= 8 else ""
                    _page.append({
                        "date":   date_str,
                        "time":   t,
                        "open":   op,
                        "high":   hi,
                        "low":    lo,
                        "close":  cl,
                        "volume": vol,
                    })

            self.api.set_input_value("종목코드", self.code)
            self.api.set_input_value("시간단위", self.timeframe)
            tr_resp = self.api.comm_rq_data("분봉조회", "opt50029", prev_next, "4000",
                                            on_data=_read_page)
            rows.extend(page_rows)

            # 연속조회 여부 확인 (prev_next=="2" 이면 더 오래된 데이터 존재)
            if str(tr_resp.get("prev_next", "0")) == "2" and len(rows) < count:
                prev_next = 2
                logger.debug(f"연속조회 (현재 {len(rows)}개)")
            else:
                break

        # 현재 형성 중인 분봉만 제외 — 완성된 당일 봉은 포함 (임의 시각 시작 지원)
        # 예) 10:33:45 시작 → 09:00~10:32 봉은 포함, 10:33봉만 제외
        now = datetime.now()
        current_bar_ts = now.strftime("%Y%m%d%H%M") + "00"  # "YYYYMMDDHHmm00"
        before = len(rows)
        rows = [r for r in rows if r["time"] < current_bar_ts]
        excluded = before - len(rows)
        if excluded:
            logger.info(f"현재 형성 중인 봉({current_bar_ts[:12]}) {excluded}개 제외")

        # 키움 TR은 최신→과거 순이므로 역순 정렬
        rows.reverse()
        for r in rows:
            self._bars.append(r)

        logger.info(f"과거 데이터 로딩 완료: {len(rows)}개 봉")
        return self.to_dataframe()

    # ------------------------------------------------------------------ #
    # CSV 로딩 (백테스트 / 오프라인 테스트용)
    # ------------------------------------------------------------------ #
    def load_from_csv(self, path: str) -> pd.DataFrame:
        """
        CSV 파일에서 OHLCV 로딩.
        예상 컬럼: time, open, high, low, close, volume
        """
        df = pd.read_csv(path, dtype=str)
        df["open"]   = df["open"].astype(float).abs()
        df["high"]   = df["high"].astype(float).abs()
        df["low"]    = df["low"].astype(float).abs()
        df["close"]  = df["close"].astype(float).abs()
        df["volume"] = df["volume"].astype(int).abs()

        for _, row in df.iterrows():
            self._bars.append(row.to_dict())

        logger.info(f"CSV 로딩 완료: {len(self._bars)}개 봉 ({path})")
        return self.to_dataframe()

    # ------------------------------------------------------------------ #
    # 실시간 봉 추가
    # ------------------------------------------------------------------ #
    def append_bar(self, bar: dict):
        """분봉 완성 시 호출."""
        self._bars.append(bar)

    # ------------------------------------------------------------------ #
    # DataFrame 변환
    # ------------------------------------------------------------------ #
    def to_dataframe(self) -> pd.DataFrame:
        if not self._bars:
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
        df = pd.DataFrame(list(self._bars))
        df = df.reset_index(drop=True)
        return df

    # ------------------------------------------------------------------ #
    # 유틸
    # ------------------------------------------------------------------ #
    @staticmethod
    def _to_float(val: str) -> float:
        try:
            return abs(float(val.replace(",", "").strip()))
        except (ValueError, AttributeError):
            return 0.0

    @staticmethod
    def _to_int(val: str) -> int:
        try:
            return abs(int(val.replace(",", "").strip()))
        except (ValueError, AttributeError):
            return 0

    def __len__(self) -> int:
        return len(self._bars)
