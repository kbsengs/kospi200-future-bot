"""
과거 OHLCV 데이터 로딩 및 관리.

키움 opt10080 (주식분봉차트) / opt50028 (선물분봉차트) TR을 사용하여
초기 히스토리를 로딩하고, 실시간 봉 완성 시 롤링 업데이트한다.
"""

from collections import deque
from datetime import datetime
from typing import Optional

import pandas as pd
from loguru import logger

from kiwoom.api import KiwoomAPI


# 최대 보관 봉 수 (메모리 절약)
MAX_BARS = 300


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
        opt50028 (선물분봉차트조회) TR로 과거 분봉 데이터 로딩.

        키움 TR 필드:
          입력: 종목코드, 틱범위(분), 수정주가구분
          출력: 체결시간, 시가, 고가, 저가, 현재가(종가), 거래량
        """
        logger.info(f"과거 데이터 로딩 시작: {self.code} {self.timeframe}분봉 {count}개")

        self.api.set_input_value("종목코드", self.code)
        self.api.set_input_value("틱범위", self.timeframe)
        self.api.set_input_value("수정주가구분", "1")
        self.api.comm_rq_data("분봉조회", "opt50028", 0, "4000")

        rows = []
        cnt = self.api.get_repeat_cnt("opt50028", "opt50028")
        for i in range(min(cnt, count)):
            time_str = self.api.get_comm_data("opt50028", "opt50028", i, "체결시간")
            open_    = self._to_float(self.api.get_comm_data("opt50028", "opt50028", i, "시가"))
            high     = self._to_float(self.api.get_comm_data("opt50028", "opt50028", i, "고가"))
            low      = self._to_float(self.api.get_comm_data("opt50028", "opt50028", i, "저가"))
            close    = self._to_float(self.api.get_comm_data("opt50028", "opt50028", i, "현재가"))
            volume   = self._to_int(self.api.get_comm_data("opt50028", "opt50028", i, "거래량"))

            # time_str 형식: "YYYYMMDDHHmmss" → 날짜 추출
            t = time_str.strip()
            date_str = f"{t[:4]}/{t[4:6]}/{t[6:8]}" if len(t) >= 8 else ""
            rows.append({
                "date":   date_str,
                "time":   t,
                "open":   open_,
                "high":   high,
                "low":    low,
                "close":  close,
                "volume": volume,
            })

        # 키움 TR은 최신→과거 순으로 반환하므로 역순 정렬
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
