"""
api/routers/optimiser.py
-------------------------
Portfolio optimiser endpoints -- advisor-only.

Routes:
  POST /optimiser/parse-constraints  -> NL -> OptimiserConstraints via Claude
  POST /optimiser/run                -> CVXPY max-Sharpe or min-variance
  POST /optimiser/run-stream         -> same + streams Claude explanation
  GET  /optimiser/frontier/{id}      -> efficient frontier stub

All runs logged to agent_runs. Results NOT auto-applied -- advisor reviews.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse

from api.dependencies import require_advisor
from api.audit import log_agent_run
from api.schemas.optimiser import (
    OptimiserConstraintsBody, OptimiserRunBody, ParsedConstraintsResponse,
    OptimiserResultResponse, FundWeightItem, EfficientFrontierResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/optimiser", tags=["optimiser"])


@router.post("/parse-constraints", response_model=ParsedConstraintsResponse)
def parse_constraints(body: OptimiserConstraintsBody, user: Annotated[dict, Depends(require_advisor)]):
    try:
        from ai.claude_advisor import parse_optimiser_constraints
        constraints = parse_optimiser_constraints(body.natural_language)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Claude parsing failed: {exc}")
    return ParsedConstraintsResponse(
        min_funds=constraints.min_funds, max_funds=constraints.max_funds,
        min_weight=constraints.min_weight, max_weight=constraints.max_weight,
        risk_free_rate=constraints.risk_free_rate, raw_text=body.natural_language,
    )


@router.post("/run", response_model=OptimiserResultResponse)
def run_optimiser(body: OptimiserRunBody, user: Annotated[dict, Depends(require_advisor)]):
    from engine.optimiser_engine import FundStats, OptimiserConstraints, optimise_portfolio
    fund_stats = [FundStats(scheme_code=f.scheme_code, scheme_name=f.scheme_name,
                            expected_return=f.expected_return, volatility=f.volatility,
                            sharpe_ratio=f.sharpe_ratio) for f in body.funds]
    constraints = OptimiserConstraints(min_funds=body.min_funds, max_funds=body.max_funds,
                                       min_weight=body.min_weight, max_weight=body.max_weight)
    if body.natural_language_constraints:
        try:
            from ai.claude_advisor import parse_optimiser_constraints
            constraints = parse_optimiser_constraints(body.natural_language_constraints)
        except Exception as exc:
            logger.warning("NL constraint parsing failed, using structured fields: %s", exc)
    try:
        result = optimise_portfolio(funds=fund_stats, correlation_matrix=body.correlation_matrix,
                                    constraints=constraints, objective=body.objective)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Optimiser error: {exc}")
    log_agent_run(
        agent_name="optimiser_engine", trigger_type="manual", client_id=body.client_id,
        inputs_summary=f"{len(body.funds)} funds, objective={body.objective}",
        decision_made=f"Optimal weights computed, Sharpe={result.portfolio_sharpe:.3f}",
        action_taken="Weights returned to advisor for review -- not applied automatically",
        approval_status="not_required",
    )
    weights = [FundWeightItem(scheme_code=w.scheme_code, scheme_name=w.scheme_name,
                              weight=round(w.weight, 4), weight_pct=round(w.weight * 100, 2))
               for w in result.weights]
    return OptimiserResultResponse(
        objective=body.objective, weights=weights,
        expected_portfolio_return=round(result.expected_portfolio_return * 100, 2),
        portfolio_volatility=round(result.portfolio_volatility * 100, 2),
        portfolio_sharpe=round(result.portfolio_sharpe, 3), solver_used=result.solver_used,
    )


@router.post("/run-stream")
def run_optimiser_with_explanation(body: OptimiserRunBody, user: Annotated[dict, Depends(require_advisor)]):
    from engine.optimiser_engine import FundStats, OptimiserConstraints, optimise_portfolio
    from ai.claude_advisor import explain_portfolio_optimisation
    fund_stats = [FundStats(scheme_code=f.scheme_code, scheme_name=f.scheme_name,
                            expected_return=f.expected_return, volatility=f.volatility,
                            sharpe_ratio=f.sharpe_ratio) for f in body.funds]
    constraints = OptimiserConstraints(min_funds=body.min_funds, max_funds=body.max_funds,
                                       min_weight=body.min_weight, max_weight=body.max_weight)
    try:
        result = optimise_portfolio(funds=fund_stats, correlation_matrix=body.correlation_matrix,
                                    constraints=constraints, objective=body.objective)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Optimiser error: {exc}")
    def _stream():
        try:
            for chunk in explain_portfolio_optimisation(funds=fund_stats, result=result,
                                                        constraints=constraints, objective=body.objective):
                yield chunk
        except Exception as exc:
            yield f"\n[Explanation error: {exc}]"
    return StreamingResponse(_stream(), media_type="text/plain")


@router.get("/frontier/{client_id}", response_model=EfficientFrontierResponse)
def get_efficient_frontier(client_id: int, user: Annotated[dict, Depends(require_advisor)]):
    raise HTTPException(status_code=404,
                        detail="No cached frontier. Run the optimiser first via POST /optimiser/run.")
