"""
두 전략 비교 백테스트.

같은 데이터로 기존 Squeeze 전략과 브랜도 전략을 동시에 실행해
성과 지표를 나란히 비교한다.

실행:
    python -m backtest.compare --csv data/sample.csv
    python -m backtest.compare --csv data/sample_2000.csv
"""

import argparse

import pandas as pd

from backtest.engine import BacktestEngine


def load_real_data(csv_path: str) -> pd.DataFrame:
    """
    키움에서 내보낸 실제 데이터 로딩 및 변환.
    입력 컬럼: 날짜, 시간, 시가, 고가, 저가, 종가, 거래량 (최신→과거 역순)
    출력 컬럼: time(YYYYMMDDHHMI), open, high, low, close, volume (과거→최신)
    """
    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    # 한글 컬럼 → 영문 매핑
    col_map = {
        "날짜": "date_str", "시간": "time_str",
        "시가": "open", "고가": "high", "저가": "low",
        "종가": "close", "거래량": "volume",
    }
    df = df.rename(columns=col_map)

    # time 컬럼 생성: YYYYMMDDHHMI
    date_part = df["date_str"].str.replace("/", "", regex=False)          # 2025/12/19 → 20251219
    time_part = df["time_str"].str.replace(":", "", regex=False).str[:4]  # 15:45:00 → 1545
    df["time"] = (date_part + time_part).astype(str)

    df = df[["time", "open", "high", "low", "close", "volume"]].copy()
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float).abs()
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int).abs()

    # 역순 정렬 (최신→과거 → 과거→최신)
    df = df.iloc[::-1].reset_index(drop=True)
    return df


def load_data(csv_path: str) -> pd.DataFrame:
    """CSV 형식 자동 감지 후 로딩."""
    with open(csv_path, encoding="utf-8-sig") as f:
        header = f.readline()
    if "날짜" in header or "시가" in header:
        return load_real_data(csv_path)

    df = pd.read_csv(csv_path)
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float).abs()
    df["volume"] = df["volume"].astype(int).abs()
    return df


def run_comparison(csv_path: str) -> None:
    df = load_data(csv_path)

    engine_sq = BacktestEngine(strategy="squeeze")
    engine_br = BacktestEngine(strategy="brando")

    result_sq = engine_sq.run(df)
    result_br = engine_br.run(df)

    # ---- 비교 테이블 출력 ----
    print("\n" + "=" * 62)
    print("  전략 비교 결과")
    print("=" * 62)
    print(f"  {'항목':<18}  {'Squeeze 전략':>16}  {'브랜도 전략':>16}")
    print("-" * 62)

    metrics = [
        ("총 거래 수",    f"{result_sq.total_trades}",
                          f"{result_br.total_trades}"),
        ("승률",          f"{result_sq.win_rate:.1f}%",
                          f"{result_br.win_rate:.1f}%"),
        ("총 손익(원)",   f"{result_sq.total_pnl:,.0f}",
                          f"{result_br.total_pnl:,.0f}"),
        ("손익비(PF)",    f"{result_sq.profit_factor:.2f}",
                          f"{result_br.profit_factor:.2f}"),
        ("최대MDD(원)",   f"{result_sq.max_drawdown:,.0f}",
                          f"{result_br.max_drawdown:,.0f}"),
    ]

    for name, val_sq, val_br in metrics:
        print(f"  {name:<18}  {val_sq:>16}  {val_br:>16}")

    print("=" * 62)

    # ---- 청산 사유 분포 ----
    def reason_dist(result):
        from collections import Counter
        return Counter(t.exit_reason for t in result.trades)

    reasons_sq = reason_dist(result_sq)
    reasons_br = reason_dist(result_br)
    all_reasons = sorted(set(list(reasons_sq.keys()) + list(reasons_br.keys())))

    print("\n  청산 사유 분포")
    print(f"  {'사유':<18}  {'Squeeze':>16}  {'브랜도':>16}")
    print("-" * 62)
    for r in all_reasons:
        print(f"  {r:<18}  {reasons_sq.get(r, 0):>16}  {reasons_br.get(r, 0):>16}")
    print("=" * 62 + "\n")


def main():
    parser = argparse.ArgumentParser(description="두 전략 비교 백테스트")
    parser.add_argument("--csv", required=True, help="OHLCV CSV 파일 경로")
    args = parser.parse_args()
    run_comparison(args.csv)


if __name__ == "__main__":
    main()
