"""
파라미터 최적화 스윕.

백테스트를 다양한 파라미터 조합으로 실행하여 최적 설정을 탐색한다.

실행:
    python -m backtest.param_sweep --csv data/sample_2000.csv
"""

import argparse
import itertools
from dataclasses import dataclass

import pandas as pd
from loguru import logger

from backtest.engine import BacktestEngine

logger.disable("__main__")
logger.disable("backtest.engine")
logger.disable("strategy.indicators")
logger.disable("strategy.signal")


@dataclass
class SweepResult:
    bb_length: int
    bb_mult: float
    kc_length: int
    kc_mult: float
    ma_fast: int
    ma_slow: int
    stop_atr_mult: float
    trades: int
    win_rate: float
    total_pnl: float
    profit_factor: float
    mdd: float


def run_sweep(df: pd.DataFrame) -> list[SweepResult]:
    param_grid = {
        "bb_length":    [15, 20],
        "bb_mult":      [2.0, 2.5],
        "kc_length":    [20],
        "kc_mult":      [1.5, 2.0],
        "ma_fast":      [5, 8],
        "ma_slow":      [20, 30],
        "stop_atr_mult": [1.5, 2.0, 2.5],
    }

    keys = list(param_grid.keys())
    values = list(param_grid.values())
    combos = list(itertools.product(*values))
    print(f"총 {len(combos)}개 파라미터 조합 테스트 중...\n")

    results = []
    for i, combo in enumerate(combos, 1):
        params = dict(zip(keys, combo))
        engine = BacktestEngine(**params)
        try:
            bt = engine.run(df)
        except Exception as e:
            continue

        if bt.total_trades == 0:
            continue

        results.append(SweepResult(
            **params,
            trades=bt.total_trades,
            win_rate=bt.win_rate,
            total_pnl=bt.total_pnl,
            profit_factor=bt.profit_factor,
            mdd=bt.max_drawdown,
        ))

        if i % 10 == 0:
            print(f"  {i}/{len(combos)} 완료...")

    return results


def main():
    parser = argparse.ArgumentParser(description="파라미터 스윕 백테스트")
    parser.add_argument("--csv", required=True, help="OHLCV CSV 파일")
    parser.add_argument("--top", type=int, default=10, help="상위 N개 출력")
    args = parser.parse_args()

    df = pd.read_csv(args.csv)
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float).abs()
    df["volume"] = df["volume"].astype(int)

    results = run_sweep(df)

    if not results:
        print("유효한 결과 없음 (거래 발생 조합이 없음)")
        return

    # 손익 기준 정렬
    results.sort(key=lambda r: r.total_pnl, reverse=True)

    print(f"\n{'='*80}")
    print(f"  파라미터 스윕 결과 (상위 {args.top}개, 총 손익 기준)")
    print(f"{'='*80}")
    print(f"{'BB':>4} {'BBm':>4} {'KC':>4} {'KCm':>4} {'MAf':>4} {'MAs':>4} {'SATRm':>5} | "
          f"{'거래':>4} {'승률':>6} {'손익':>12} {'PF':>5} {'MDD':>12}")
    print("-" * 80)
    for r in results[:args.top]:
        pf_str = f"{r.profit_factor:.2f}" if r.profit_factor < 999 else " inf"
        print(
            f"{r.bb_length:>4} {r.bb_mult:>4} {r.kc_length:>4} {r.kc_mult:>4} "
            f"{r.ma_fast:>4} {r.ma_slow:>4} {r.stop_atr_mult:>5} | "
            f"{r.trades:>4} {r.win_rate:>5.1f}% {r.total_pnl:>12,.0f} {pf_str:>5} {r.mdd:>12,.0f}"
        )
    print(f"{'='*80}\n")

    best = results[0]
    print("추천 파라미터 (최고 손익):")
    print(f"  bb_length={best.bb_length}, bb_mult={best.bb_mult}")
    print(f"  kc_length={best.kc_length}, kc_mult={best.kc_mult}")
    print(f"  ma_fast={best.ma_fast}, ma_slow={best.ma_slow}")
    print(f"  stop_atr_mult={best.stop_atr_mult}")


if __name__ == "__main__":
    main()
