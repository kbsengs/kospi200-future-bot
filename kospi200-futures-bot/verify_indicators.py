"""
지표 검증 스크립트.

TradingView Squeeze Momentum Indicator [LazyBear] 와 동일한 값이 나오는지 확인한다.

사용법:
    1. TradingView 차트에서 데이터를 CSV로 내보내거나 직접 입력한다.
    2. python verify_indicators.py --csv data/verify_sample.csv
    3. TradingView에서 확인한 모멘텀 값과 비교한다.

CSV 형식:
    time,open,high,low,close,volume
    202403070845,365.50,366.20,365.10,365.80,1234
    ...
"""

import argparse
import sys

import pandas as pd

from strategy.indicators import bollinger_bands, keltner_channel, squeeze_momentum, moving_average


def verify(csv_path: str, last_n: int = 5):
    df = pd.read_csv(csv_path)

    # 컬럼 정규화
    df.columns = [c.lower().strip() for c in df.columns]
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float).abs()
    df["volume"] = df["volume"].astype(int)

    print(f"\n데이터 로딩: {len(df)}개 봉\n")

    # --- Bollinger Bands ---
    bb = bollinger_bands(df["close"], 20, 2.0)
    print("=== Bollinger Bands (20, 2.0) - 마지막 3봉 ===")
    print(bb.tail(3).round(4).to_string())

    # --- Keltner Channel ---
    kc = keltner_channel(df["high"], df["low"], df["close"], 20, 1.5)
    print("\n=== Keltner Channel (20, 1.5) - 마지막 3봉 ===")
    print(kc.tail(3).round(4).to_string())

    # --- Squeeze 상태 ---
    sq = squeeze_momentum(df)
    print("\n=== Squeeze Momentum - 마지막 5봉 ===")
    result = sq[["squeeze_on", "squeeze_off", "momentum"]].tail(last_n)
    result = result.copy()
    result["momentum"] = result["momentum"].round(4)
    print(result.to_string())

    # --- MA ---
    ma = moving_average(df["close"], 5, 20)
    print("\n=== Moving Average (fast=5, slow=20) - 마지막 3봉 ===")
    print(ma.tail(3).round(4).to_string())

    # --- Squeeze 전환 감지 ---
    if len(sq) >= 2:
        prev_on = sq["squeeze_on"].iloc[-2]
        curr_on = sq["squeeze_on"].iloc[-1]
        curr_mom = sq["momentum"].iloc[-1]
        ma_fast = ma["ma_fast"].iloc[-1]
        ma_slow = ma["ma_slow"].iloc[-1]

        print("\n=== 최신 신호 판단 ===")
        print(f"  이전봉 squeeze_on : {prev_on}")
        print(f"  현재봉 squeeze_on : {curr_on}")
        print(f"  현재봉 momentum   : {curr_mom:.4f}")
        print(f"  MA fast/slow      : {ma_fast:.2f} / {ma_slow:.2f}")

        squeeze_fired = prev_on and not curr_on
        print(f"\n  Squeeze OFF 전환  : {squeeze_fired}")
        if squeeze_fired:
            if curr_mom > 0 and ma_fast > ma_slow:
                print("  → 신호: LONG 진입 조건 충족")
            elif curr_mom < 0 and ma_fast < ma_slow:
                print("  → 신호: SHORT 진입 조건 충족")
            else:
                print("  → 신호: MA 필터 미통과 (진입 없음)")
        else:
            print("  → 신호: Squeeze 압축 중 or 이미 OFF 상태")

    print("\n검증 완료. TradingView 값과 비교하세요.")


def create_sample_csv(path: str):
    """검증용 샘플 CSV 생성 (실제 데이터로 교체 필요)."""
    import numpy as np
    np.random.seed(42)

    n = 60
    base = 360.0
    prices = base + np.cumsum(np.random.randn(n) * 0.5)

    rows = []
    for i, p in enumerate(prices):
        o = p + np.random.randn() * 0.2
        h = max(o, p) + abs(np.random.randn() * 0.3)
        l = min(o, p) - abs(np.random.randn() * 0.3)
        c = p
        v = int(abs(np.random.randn() * 500 + 1000))
        rows.append({"time": f"20240307{8*60+45+i:04d}", "open": round(o,2),
                     "high": round(h,2), "low": round(l,2), "close": round(c,2), "volume": v})

    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)
    print(f"샘플 CSV 생성: {path} ({n}개 봉)")
    print("※ 실제 TradingView 데이터로 교체 후 검증하세요.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Squeeze Momentum 지표 검증")
    parser.add_argument("--csv", default="data/verify_sample.csv", help="OHLCV CSV 파일")
    parser.add_argument("--create-sample", action="store_true", help="샘플 CSV 생성")
    parser.add_argument("--last-n", type=int, default=5, help="마지막 N개 봉 출력")
    args = parser.parse_args()

    if args.create_sample:
        create_sample_csv(args.csv)

    verify(args.csv, args.last_n)
