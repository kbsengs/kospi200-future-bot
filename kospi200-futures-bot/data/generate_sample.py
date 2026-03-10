"""
백테스트용 현실적 OHLCV 샘플 데이터 생성기.

Squeeze Momentum 전략 검증을 위해 저변동 → 고변동 전환 패턴을 포함한다.

실행:
    python -m data.generate_sample --out data/sample.csv --bars 500
"""

import argparse
import numpy as np
import pandas as pd


def generate_ohlcv(n_bars: int = 500, seed: int = 42) -> pd.DataFrame:
    """
    저변동(Squeeze ON) 구간과 고변동(Squeeze OFF) 구간이 반복되는 합성 데이터 생성.

    패턴:
      1. 저변동 횡보 구간 (20~40봉): Squeeze ON → BB가 KC 내부 수렴
      2. 방향성 폭발 구간 (10~20봉): 강한 추세 (상승 or 하락)
      3. 재수렴 구간 반복
    """
    rng = np.random.default_rng(seed)
    price = 360.0
    rows = []

    i = 0
    while i < n_bars:
        # 저변동 횡보 구간 (Squeeze ON 유도)
        squeeze_len = int(rng.integers(25, 45))
        for _ in range(squeeze_len):
            if i >= n_bars:
                break
            noise = rng.normal(0, 0.15)
            price += noise
            o = price + rng.normal(0, 0.05)
            h = max(o, price) + abs(rng.normal(0, 0.08))
            l = min(o, price) - abs(rng.normal(0, 0.08))
            c = price
            v = int(abs(rng.normal(800, 200)))
            rows.append(_make_row(i, o, h, l, c, v))
            i += 1

        # 방향성 폭발 구간 (Squeeze OFF 유도)
        burst_len = int(rng.integers(10, 20))
        direction = rng.choice([-1, 1])
        for j in range(burst_len):
            if i >= n_bars:
                break
            move = rng.normal(0.6, 0.2) * direction
            price += move
            o = price - move * 0.3 + rng.normal(0, 0.1)
            h = max(o, price) + abs(rng.normal(0, 0.15))
            l = min(o, price) - abs(rng.normal(0, 0.1))
            c = price
            v = int(abs(rng.normal(2000, 500)))
            rows.append(_make_row(i, o, h, l, c, v))
            i += 1

    df = pd.DataFrame(rows)
    return df


def _make_row(idx: int, o: float, h: float, l: float, c: float, v: int) -> dict:
    # 시간: 08:45 시작, 1분씩 증가 (장 시간: 08:45~15:45 = 420분)
    minutes_offset = idx % 420
    hour = 8 + (45 + minutes_offset) // 60
    minute = (45 + minutes_offset) % 60
    day = 20240307 + (idx // 420)
    time_str = f"{day}{hour:02d}{minute:02d}"
    return {
        "time":   time_str,
        "open":   round(abs(o), 2),
        "high":   round(abs(h), 2),
        "low":    round(abs(l), 2),
        "close":  round(abs(c), 2),
        "volume": max(v, 1),
    }


def main():
    parser = argparse.ArgumentParser(description="백테스트용 OHLCV 샘플 생성")
    parser.add_argument("--out",  default="data/sample.csv", help="출력 파일 경로")
    parser.add_argument("--bars", type=int, default=500, help="총 봉 수")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    df = generate_ohlcv(args.bars, args.seed)
    df.to_csv(args.out, index=False)
    print(f"샘플 데이터 생성 완료: {args.out} ({len(df)}봉)")
    print(df.tail(3).to_string(index=False))


if __name__ == "__main__":
    main()
