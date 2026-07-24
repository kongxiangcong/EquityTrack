from __future__ import annotations

import json

import pandas as pd

from backtest.engines.base import _align
from backtest.engines.china_a import ChinaAEngine, _price_limit
from backtest.models import Position, TradeRecord
from backtest.validation import (
    bootstrap_sharpe_ci,
    monte_carlo_test,
    walk_forward_analysis,
)


def trade(index: int, pnl: float) -> TradeRecord:
    entry = pd.Timestamp("2026-01-01") + pd.Timedelta(days=index * 2)
    return TradeRecord(
        symbol="FIXTURE",
        direction=1,
        entry_price=10.0,
        exit_price=10.0 + pnl / 100.0,
        entry_time=entry,
        exit_time=entry + pd.Timedelta(days=1),
        size=100.0,
        leverage=1.0,
        pnl=pnl,
        pnl_pct=pnl / 1000.0,
        exit_reason="signal",
        holding_bars=1,
        commission=1.0,
    )


def main() -> None:
    checks: list[str] = []
    trades = [
        trade(index, pnl)
        for index, pnl in enumerate((100, -40, 80, -20, 60, -10, 50, -30))
    ]
    mc_same_a = monte_carlo_test(trades, 10000.0, n_simulations=500, seed=42)
    mc_same_b = monte_carlo_test(trades, 10000.0, n_simulations=500, seed=42)
    mc_other_seed = monte_carlo_test(trades, 10000.0, n_simulations=500, seed=43)
    assert mc_same_a == mc_same_b
    checks.append("trade-order permutation is deterministic for the same seed")
    assert mc_same_a != mc_other_seed
    checks.append("trade-order permutation varies across seeds")
    assert "seed" not in mc_same_a and "algorithm" not in mc_same_a
    checks.append("Monte Carlo result omits seed and algorithm identity")
    assert "convergence" not in mc_same_a
    checks.append("Monte Carlo result has no convergence diagnostic")

    equity = pd.Series(
        [100.0, 101.0, 100.5, 102.0, 101.5, 103.0, 102.0, 104.0, 103.5, 105.0],
        index=pd.date_range("2026-01-01", periods=10, freq="D"),
    )
    bootstrap_same_a = bootstrap_sharpe_ci(equity, n_bootstrap=500, seed=42)
    bootstrap_same_b = bootstrap_sharpe_ci(equity, n_bootstrap=500, seed=42)
    bootstrap_other_seed = bootstrap_sharpe_ci(equity, n_bootstrap=500, seed=43)
    assert bootstrap_same_a == bootstrap_same_b
    checks.append("IID bootstrap is deterministic for the same seed")
    assert bootstrap_same_a != bootstrap_other_seed
    checks.append("IID bootstrap varies across seeds")
    assert not {"seed", "algorithm", "block_length", "convergence"} & set(
        bootstrap_same_a
    )
    checks.append("bootstrap result omits seed, algorithm, dependence and convergence")

    walk_forward = walk_forward_analysis(equity, trades, n_windows=5)
    assert not {
        "train_window",
        "test_window",
        "refit",
        "embargo",
        "in_sample",
        "out_of_sample",
    } & set(walk_forward)
    checks.append("walk-forward output is only a post-hoc window split")

    dates = pd.date_range("2026-01-05", periods=4, freq="D")
    frame = pd.DataFrame(
        {
            "open": [10.0, 11.0, 12.0, 13.0],
            "high": [10.5, 11.5, 12.5, 13.5],
            "low": [9.5, 10.5, 11.5, 12.5],
            "close": [10.1, 11.1, 12.1, 13.1],
            "volume": [1000, 1000, 1000, 1000],
        },
        index=dates,
    )
    signal = pd.Series([1.0, 0.0, -1.0, 1.0], index=dates)
    _, _, positions, _ = _align(
        {"000001.SZ": frame},
        {"000001.SZ": signal},
        ["000001.SZ"],
    )
    assert positions["000001.SZ"].tolist() == [0.0, 1.0, 0.0, -1.0]
    checks.append("per-symbol signal alignment applies a one-bar lag")

    engine = ChinaAEngine({})
    engine.positions["000001.SZ"] = Position(
        symbol="000001.SZ",
        direction=1,
        entry_price=10.0,
        entry_time=pd.Timestamp("2026-01-05"),
        size=100.0,
    )
    same_day = pd.Series(
        {"close": 10.0, "pre_close": 10.0}, name=pd.Timestamp("2026-01-05")
    )
    next_day = pd.Series(
        {"close": 10.0, "pre_close": 10.0}, name=pd.Timestamp("2026-01-06")
    )
    assert engine.can_execute("000001.SZ", 0, same_day) is False
    assert engine.can_execute("000001.SZ", 0, next_day) is True
    checks.append("A-share skeleton blocks same-day sale and allows next-day sale")
    assert engine.round_size(199, 10.0) == 100
    checks.append("A-share skeleton rounds buy size to 100-share lots")
    assert _price_limit("600000.SH") == 0.10
    assert _price_limit("ST-600000.SH") == 0.10
    checks.append("A-share price-limit helper cannot identify ST 5-percent regime")

    result = {
        "suite": "vibe-trading-algorithm-adversarial",
        "passed": len(checks),
        "failed": 0,
        "checks": checks,
        "monte_carlo": {
            "same_seed_equal": mc_same_a == mc_same_b,
            "different_seed_equal": mc_same_a == mc_other_seed,
            "result_keys": sorted(mc_same_a),
            "method_identity": "trade_pnl_order_permutation",
        },
        "bootstrap": {
            "same_seed_equal": bootstrap_same_a == bootstrap_same_b,
            "different_seed_equal": bootstrap_same_a == bootstrap_other_seed,
            "result_keys": sorted(bootstrap_same_a),
            "method_identity": "iid_single_bar_return_resampling",
        },
        "walk_forward": {
            "result_keys": sorted(walk_forward),
            "method_identity": "post_hoc_non_overlapping_window_split",
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
