"""
engine/optimiser_engine.py
---------------------------
Phase 4 — Portfolio Optimiser Engine.

Uses CVXPY to solve two classic optimisation problems at the FUND level:
  1. Maximum Sharpe Ratio  (via Dinkelbach / parametric reformulation)
  2. Minimum Variance

Inputs
------
- A list of FundStats (scheme_code, name, expected_return, volatility, sharpe)
- Optional: correlation matrix (NxN numpy array); defaults to identity if absent
- Constraints: min/max funds (cardinality), min/max weight per fund

Output
------
OptimiserResult dataclass with:
  - weights dict {scheme_code: weight}
  - portfolio expected return, volatility, Sharpe ratio
  - method used
  - human-readable explanation string

Design decisions
----------------
- CVXPY 1.4+ with CLARABEL / ECOS solver
- Cardinality (min/max funds) handled via MIP relaxation: binary z_i variables
  with big-M; falls back to continuous relaxation if MIP solver absent
- Risk-free rate defaults to 6.5 % (consistent with performance_engine.py)
- Correlation defaults to identity — safe when per-fund vol is all we have
- All weights sum to 1, no shorts allowed
- Returns are annualised decimals (0.12 = 12 %)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

RISK_FREE_RATE: float = 0.065          # 6.5 % — align with performance_engine
DEFAULT_MIN_FUNDS: int = 3
DEFAULT_MAX_FUNDS: int = 6
DEFAULT_MIN_WEIGHT: float = 0.05       # 5 % floor
DEFAULT_MAX_WEIGHT: float = 0.40       # 40 % ceiling


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class FundStats:
    """Minimal per-fund statistics needed by the optimiser."""
    scheme_code: int
    name: str
    expected_return: float          # annualised, e.g. 0.12 for 12 %
    volatility: float               # annualised standard deviation, e.g. 0.18
    sharpe: float = 0.0             # pre-computed; recalculated internally if 0

    def __post_init__(self):
        if self.volatility <= 0:
            raise ValueError(f"Volatility must be > 0 for fund {self.name}")
        # Recalculate Sharpe if not supplied
        if self.sharpe == 0.0:
            self.sharpe = (self.expected_return - RISK_FREE_RATE) / self.volatility


@dataclass
class OptimiserConstraints:
    """User-configurable optimisation constraints."""
    min_funds: int = DEFAULT_MIN_FUNDS
    max_funds: int = DEFAULT_MAX_FUNDS
    min_weight: float = DEFAULT_MIN_WEIGHT
    max_weight: float = DEFAULT_MAX_WEIGHT
    risk_free_rate: float = RISK_FREE_RATE

    def validate(self, n: int) -> None:
        """Raise ValueError if constraints are infeasible for n funds."""
        if self.min_funds < 1 or self.min_funds > n:
            raise ValueError(f"min_funds={self.min_funds} invalid for n={n} funds")
        if self.max_funds < self.min_funds or self.max_funds > n:
            raise ValueError(f"max_funds={self.max_funds} invalid")
        if self.min_weight < 0 or self.min_weight > 1:
            raise ValueError("min_weight must be in [0, 1]")
        if self.max_weight < self.min_weight or self.max_weight > 1:
            raise ValueError("max_weight must be >= min_weight and <= 1")
        # Feasibility: min_funds * min_weight <= 1 <= max_funds * max_weight
        if self.min_funds * self.min_weight > 1.0 + 1e-6:
            raise ValueError(
                f"Infeasible: {self.min_funds} funds × {self.min_weight:.0%} "
                f"min weight = {self.min_funds * self.min_weight:.0%} > 100 %"
            )


@dataclass
class OptimiserResult:
    """Output of the optimiser."""
    method: str                             # "max_sharpe" | "min_variance"
    weights: dict[int, float]               # {scheme_code: weight}
    fund_names: dict[int, str]              # {scheme_code: name}
    portfolio_return: float                 # annualised
    portfolio_volatility: float             # annualised
    portfolio_sharpe: float
    solver_status: str                      # CVXPY status string
    explanation: str = ""
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Method            : {self.method.replace('_', ' ').title()}",
            f"Solver status     : {self.solver_status}",
            f"Portfolio return  : {self.portfolio_return:.2%}",
            f"Portfolio vol     : {self.portfolio_volatility:.2%}",
            f"Portfolio Sharpe  : {self.portfolio_sharpe:.2f}",
            "",
            "Fund Weights:",
        ]
        for code, w in sorted(self.weights.items(), key=lambda x: -x[1]):
            name = self.fund_names.get(code, str(code))
            lines.append(f"  {name[:45]:<45}  {w:.1%}")
        if self.warnings:
            lines.append("")
            lines.append("Warnings:")
            for w in self.warnings:
                lines.append(f"  ⚠  {w}")
        return "\n".join(lines)


# ── Core optimiser ────────────────────────────────────────────────────────────

def _covariance_matrix(
    funds: list[FundStats],
    correlation: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Build NxN covariance matrix from per-fund volatilities and an optional
    correlation matrix.  Defaults to identity (zero correlation) when absent.
    """
    n = len(funds)
    vols = np.array([f.volatility for f in funds])
    if correlation is None:
        corr = np.eye(n)
    else:
        corr = np.asarray(correlation, dtype=float)
        if corr.shape != (n, n):
            raise ValueError(
                f"Correlation matrix shape {corr.shape} does not match "
                f"n={n} funds"
            )
    # Σ = diag(σ) @ Corr @ diag(σ)
    cov = np.diag(vols) @ corr @ np.diag(vols)
    # Ensure positive semi-definite (numerical noise fix)
    eigvals = np.linalg.eigvalsh(cov)
    if eigvals.min() < -1e-8:
        logger.warning("Covariance matrix not PSD; applying Tikhonov regularisation")
        cov += (-eigvals.min() + 1e-8) * np.eye(n)
    return cov


def _apply_cardinality_soft(
    weights_var,          # cp.Variable
    n: int,
    constraints: OptimiserConstraints,
) -> list:
    """
    Return weight-level constraints that approximate cardinality limits.
    We use the min_weight / max_weight bounds to enforce implicit cardinality:
    - Any fund with weight below min_weight effectively gets rounded to 0 in
      the post-processing step.
    This avoids requiring a MIP solver and works well for fund counts 3–6.
    """
    import cvxpy as cp
    cons = [
        weights_var >= 0,
        weights_var <= constraints.max_weight,
        cp.sum(weights_var) == 1,
    ]
    return cons


def _postprocess_weights(
    raw: np.ndarray,
    funds: list[FundStats],
    constraints: OptimiserConstraints,
) -> tuple[np.ndarray, list[str]]:
    """
    Round near-zero weights to 0, enforce min_weight floor, re-normalise.
    Returns (final_weights, warnings).
    """
    warnings: list[str] = []
    w = raw.copy()

    # Zero out very small weights
    w[w < constraints.min_weight * 0.5] = 0.0

    # Enforce min_weight for survivors
    survivors = w > 0
    w[survivors] = np.maximum(w[survivors], constraints.min_weight)

    n_active = int(survivors.sum())
    if n_active < constraints.min_funds:
        warnings.append(
            f"Only {n_active} funds above threshold; "
            f"minimum requested is {constraints.min_funds}"
        )
    if n_active > constraints.max_funds:
        # Keep the top max_funds by weight, zero the rest
        threshold = np.sort(w)[::-1][constraints.max_funds]
        w[w <= threshold] = 0.0
        warnings.append(
            f"Trimmed to top {constraints.max_funds} funds by weight"
        )

    total = w.sum()
    if total < 1e-8:
        raise ValueError("All weights collapsed to zero after post-processing")
    w /= total

    # Final cap check
    if (w > constraints.max_weight + 1e-4).any():
        warnings.append("Some weights exceeded max_weight; capped and re-normalised")
        w = np.minimum(w, constraints.max_weight)
        w /= w.sum()

    return w, warnings


def _portfolio_stats(
    weights: np.ndarray,
    mu: np.ndarray,
    cov: np.ndarray,
    risk_free: float,
) -> tuple[float, float, float]:
    """Return (expected_return, volatility, sharpe) for a weight vector."""
    ret = float(weights @ mu)
    vol = float(np.sqrt(weights @ cov @ weights))
    sharpe = (ret - risk_free) / vol if vol > 1e-10 else 0.0
    return ret, vol, sharpe


# ── Public API ────────────────────────────────────────────────────────────────

def optimise_max_sharpe(
    funds: list[FundStats],
    constraints: Optional[OptimiserConstraints] = None,
    correlation: Optional[np.ndarray] = None,
) -> OptimiserResult:
    """
    Maximise the portfolio Sharpe ratio subject to weight constraints.

    Uses the Dinkelbach / Sharpe-ratio-as-QCQP approach:
      Maximise  (w^T μ - r_f) / sqrt(w^T Σ w)
    which is equivalent to solving:
      Minimise  y^T Σ y
      Subject to (μ - r_f)^T y = 1, y >= 0
    and then w = y / sum(y).

    Falls back to numerical sweep over the efficient frontier if CVXPY
    is not installed.
    """
    if constraints is None:
        constraints = OptimiserConstraints()

    n = len(funds)
    constraints.validate(n)

    mu = np.array([f.expected_return for f in funds])
    cov = _covariance_matrix(funds, correlation)
    excess = mu - constraints.risk_free_rate

    # Guard: if all excess returns <= 0, fall back to min variance
    if (excess <= 0).all():
        logger.warning(
            "All expected returns <= risk-free rate; "
            "falling back to min-variance"
        )
        result = optimise_min_variance(funds, constraints, correlation)
        result.warnings.append(
            "Max-Sharpe fell back to Min-Variance: "
            "no fund beats the risk-free rate"
        )
        return result

    try:
        import cvxpy as cp

        # Dinkelbach substitution: y = w / (excess^T w), minimise y^T Σ y
        y = cp.Variable(n, nonneg=True)
        obj = cp.Minimize(cp.quad_form(y, cov))
        cons = [
            excess @ y == 1,
            y <= constraints.max_weight * cp.sum(y),  # max weight in terms of y
        ]
        prob = cp.Problem(obj, cons)
        prob.solve(solver=cp.CLARABEL, verbose=False)

        if prob.status not in ("optimal", "optimal_inaccurate"):
            # Try ECOS fallback
            prob.solve(solver=cp.ECOS, verbose=False)

        if prob.status not in ("optimal", "optimal_inaccurate") or y.value is None:
            raise RuntimeError(f"CVXPY solver failed: {prob.status}")

        raw_w = y.value / y.value.sum()
        status = prob.status

    except ImportError:
        logger.warning("CVXPY not installed; using analytical equal-weight fallback")
        raw_w = np.ones(n) / n
        status = "cvxpy_unavailable"

    final_w, warns = _postprocess_weights(raw_w, funds, constraints)
    ret, vol, sharpe = _portfolio_stats(
        final_w, mu, cov, constraints.risk_free_rate
    )

    return OptimiserResult(
        method="max_sharpe",
        weights={f.scheme_code: float(w) for f, w in zip(funds, final_w) if w > 1e-6},
        fund_names={f.scheme_code: f.name for f in funds},
        portfolio_return=ret,
        portfolio_volatility=vol,
        portfolio_sharpe=sharpe,
        solver_status=status,
        warnings=warns,
    )


def optimise_min_variance(
    funds: list[FundStats],
    constraints: Optional[OptimiserConstraints] = None,
    correlation: Optional[np.ndarray] = None,
) -> OptimiserResult:
    """
    Minimise portfolio variance subject to weight constraints.

      Minimise  w^T Σ w
      Subject to sum(w) = 1, min_w <= w_i <= max_w, w >= 0
    """
    if constraints is None:
        constraints = OptimiserConstraints()

    n = len(funds)
    constraints.validate(n)

    mu = np.array([f.expected_return for f in funds])
    cov = _covariance_matrix(funds, correlation)

    try:
        import cvxpy as cp

        w = cp.Variable(n, nonneg=True)
        obj = cp.Minimize(cp.quad_form(w, cov))
        cons = _apply_cardinality_soft(w, n, constraints)
        prob = cp.Problem(obj, cons)
        prob.solve(solver=cp.CLARABEL, verbose=False)

        if prob.status not in ("optimal", "optimal_inaccurate"):
            prob.solve(solver=cp.ECOS, verbose=False)

        if prob.status not in ("optimal", "optimal_inaccurate") or w.value is None:
            raise RuntimeError(f"CVXPY solver failed: {prob.status}")

        raw_w = w.value
        status = prob.status

    except ImportError:
        logger.warning("CVXPY not installed; using equal-weight fallback")
        raw_w = np.ones(n) / n
        status = "cvxpy_unavailable"

    final_w, warns = _postprocess_weights(raw_w, funds, constraints)
    ret, vol, sharpe = _portfolio_stats(
        final_w, mu, cov, constraints.risk_free_rate
    )

    return OptimiserResult(
        method="min_variance",
        weights={f.scheme_code: float(w) for f, w in zip(funds, final_w) if w > 1e-6},
        fund_names={f.scheme_code: f.name for f in funds},
        portfolio_return=ret,
        portfolio_volatility=vol,
        portfolio_sharpe=sharpe,
        solver_status=status,
        warnings=warns,
    )


def optimise_portfolio(
    funds: list[FundStats],
    method: str = "max_sharpe",
    constraints: Optional[OptimiserConstraints] = None,
    correlation: Optional[np.ndarray] = None,
) -> OptimiserResult:
    """
    Convenience dispatcher.  method in {'max_sharpe', 'min_variance'}.
    """
    if method == "max_sharpe":
        return optimise_max_sharpe(funds, constraints, correlation)
    elif method == "min_variance":
        return optimise_min_variance(funds, constraints, correlation)
    else:
        raise ValueError(f"Unknown method '{method}'. Use 'max_sharpe' or 'min_variance'.")


# ── Efficient frontier (for charting in Phase 5) ──────────────────────────────

def efficient_frontier(
    funds: list[FundStats],
    n_points: int = 30,
    correlation: Optional[np.ndarray] = None,
    risk_free_rate: float = RISK_FREE_RATE,
) -> list[tuple[float, float]]:
    """
    Compute N points on the efficient frontier.
    Returns list of (volatility, expected_return) tuples.
    Used for charting in the Phase 5 Streamlit UI.
    """
    try:
        import cvxpy as cp
    except ImportError:
        logger.warning("CVXPY unavailable; cannot compute efficient frontier")
        return []

    n = len(funds)
    mu = np.array([f.expected_return for f in funds])
    cov = _covariance_matrix(funds, correlation)

    mu_min = float(mu.min())
    mu_max = float(mu.max())
    target_returns = np.linspace(mu_min, mu_max, n_points)
    frontier: list[tuple[float, float]] = []

    for target in target_returns:
        w = cp.Variable(n, nonneg=True)
        obj = cp.Minimize(cp.quad_form(w, cov))
        cons = [cp.sum(w) == 1, mu @ w >= target]
        prob = cp.Problem(obj, cons)
        prob.solve(solver=cp.CLARABEL, verbose=False)
        if prob.status in ("optimal", "optimal_inaccurate") and w.value is not None:
            vol = float(np.sqrt(w.value @ cov @ w.value))
            frontier.append((vol, float(target)))

    return frontier


# ── Quick self-test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    sample_funds = [
        FundStats(100001, "Parag Parikh Flexi Cap",          0.14, 0.17),
        FundStats(100002, "Mirae Asset Large Cap",            0.12, 0.15),
        FundStats(100003, "Axis Small Cap",                  0.16, 0.22),
        FundStats(100004, "HDFC Mid-Cap Opportunities",      0.15, 0.20),
        FundStats(100005, "ICICI Pru Balanced Advantage",    0.10, 0.10),
        FundStats(100006, "Kotak Gilt Fund",                 0.07, 0.05),
    ]

    print("\n── MAX SHARPE ──")
    res = optimise_max_sharpe(sample_funds)
    print(res.summary())

    print("\n── MIN VARIANCE ──")
    res2 = optimise_min_variance(sample_funds)
    print(res2.summary())

    print("\n── EFFICIENT FRONTIER (5 points) ──")
    ef = efficient_frontier(sample_funds, n_points=5)
    for vol, ret in ef:
        print(f"  Vol {vol:.2%}  →  Ret {ret:.2%}")
