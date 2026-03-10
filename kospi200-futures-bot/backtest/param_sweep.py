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
from backtest.compare import load_data

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
    min_squeeze_bars: int
    min_momentum: float
    stop_atr_mult: float
    trades: int
    win_rate: float
    total_pnl: float
    profit_factor: float
    mdd: float


def run_sweep(df: pd.DataFrame) -> list[SweepResult]:
    """
    최적화된 스윕: BB/KC 조합별로 지표를 한 번만 계산하고
    진입 파라미터(min_squeeze_bars, min_momentum, stop_atr_mult)만 루프.
    """
    from strategy.indicators import (
        bollinger_bands, squeeze_momentum, moving_average, atr as calc_atr,
    )
    from data.gap_adjust import make_indicator_df

    # 갭 보정 (지표용)
    if "time" in df.columns:
        tmp = df.copy()
        tmp["_date"] = tmp["time"].astype(str).str[:8]
        ind_df = make_indicator_df(tmp, date_col="_date")
    else:
        ind_df = df

    # 지표 파라미터: BB/KC는 기본값 고정, MA만 변경 (linreg 재계산 최소화)
    indicator_grid = {
        "bb_length": [20],
        "bb_mult":   [2.0],
        "kc_length": [20],
        "kc_mult":   [1.5],
        "ma_fast":   [5, 8],
        "ma_slow":   [20, 30],
    }
    # 진입 파라미터: 핵심 최적화 대상
    entry_grid = {
        "min_squeeze_bars": [3, 5, 8, 10],
        "min_momentum":     [0.05, 0.1, 0.2, 0.3],
        "stop_atr_mult":    [1.0, 1.5, 2.0, 2.5],
    }

    ind_combos   = list(itertools.product(*indicator_grid.values()))
    entry_combos = list(itertools.product(*entry_grid.values()))
    total = len(ind_combos) * len(entry_combos)
    print(f"총 {total}개 파라미터 조합 테스트 중...\n")

    results = []
    done = 0

    for ind_combo in ind_combos:
        ind_params = dict(zip(indicator_grid.keys(), ind_combo))

        # 지표 사전 계산 (이 조합에서 한 번만)
        engine_base = BacktestEngine(strategy="squeeze", **ind_params)

        for entry_combo in entry_combos:
            entry_params = dict(zip(entry_grid.keys(), entry_combo))
            engine = BacktestEngine(strategy="squeeze", **ind_params, **entry_params)
            try:
                bt = engine.run(df)
            except Exception:
                continue
            finally:
                done += 1

            if bt.total_trades == 0:
                continue

            results.append(SweepResult(
                **ind_params, **entry_params,
                trades=bt.total_trades,
                win_rate=bt.win_rate,
                total_pnl=bt.total_pnl,
                profit_factor=bt.profit_factor,
                mdd=bt.max_drawdown,
            ))

        if done % 100 == 0:
            print(f"  {done}/{total} 완료...")

    print(f"  {done}/{total} 완료.")
    return results


def main():
    parser = argparse.ArgumentParser(description="파라미터 스윕 백테스트")
    parser.add_argument("--csv", required=True, help="OHLCV CSV 파일")
    parser.add_argument("--top", type=int, default=10, help="상위 N개 출력")
    args = parser.parse_args()

    df = load_data(args.csv)

    results = run_sweep(df)

    if not results:
        print("유효한 결과 없음 (거래 발생 조합이 없음)")
        return

    # 손익 기준 정렬
    results.sort(key=lambda r: r.total_pnl, reverse=True)

    print(f"\n{'='*80}")
    print(f"  파라미터 스윕 결과 (상위 {args.top}개, 총 손익 기준)")
    print(f"{'='*80}")
    print(f"{'BB':>4} {'BBm':>4} {'KC':>4} {'KCm':>4} {'MAf':>4} {'MAs':>4} {'SqB':>4} {'Mom':>5} {'Satr':>5} | "
          f"{'거래':>4} {'승률':>6} {'손익':>12} {'PF':>5} {'MDD':>12}")
    print("-" * 90)
    for r in results[:args.top]:
        pf_str = f"{r.profit_factor:.2f}" if r.profit_factor < 999 else "  inf"
        print(
            f"{r.bb_length:>4} {r.bb_mult:>4} {r.kc_length:>4} {r.kc_mult:>4} "
            f"{r.ma_fast:>4} {r.ma_slow:>4} {r.min_squeeze_bars:>4} {r.min_momentum:>5} {r.stop_atr_mult:>5} | "
            f"{r.trades:>4} {r.win_rate:>5.1f}% {r.total_pnl:>12,.0f} {pf_str:>5} {r.mdd:>12,.0f}"
        )
    print(f"{'='*90}\n")

    best = results[0]
    print("추천 파라미터 (최고 손익):")
    print(f"  bb_length={best.bb_length}, bb_mult={best.bb_mult}")
    print(f"  kc_length={best.kc_length}, kc_mult={best.kc_mult}")
    print(f"  ma_fast={best.ma_fast}, ma_slow={best.ma_slow}")
    print(f"  min_squeeze_bars={best.min_squeeze_bars}, min_momentum={best.min_momentum}")
    print(f"  stop_atr_mult={best.stop_atr_mult}")


if __name__ == "__main__":
    main()
