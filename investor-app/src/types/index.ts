/**
 * types/index.ts — Shared TypeScript types mirroring FastAPI schemas.
 * Verified against api/schemas/*.py — June 2026.
 */

export interface OtpRequestPayload  { email: string; phone?: string }
export interface OtpVerifyPayload   { email: string; otp: string }
export interface AuthTokens         { access_token: string; refresh_token: string; token_type: string }

export interface Client {
  id: number; name: string; email: string; phone: string; age: number;
  annual_income: number; monthly_income: number; dependants: number; pan: string;
  risk_profile: string | null; risk_score: number | null;
  onboarding_status?: string; advisor_id?: number | null;
}

export type GoalType = "retirement" | "education" | "house" | "emergency" | "wedding" | "travel" | "custom";

export interface Goal {
  id: number; client_id: number; goal_name: string; goal_type: GoalType;
  target_amount: number; target_year: number; current_savings: number;
  monthly_sip: number; priority: number;
  // feasibility NOT returned by GET /goals/{id} — only by POST /goals/plan
}

export interface GoalPlanRequest {
  goal_type: GoalType; goal_name: string; target_amount_today: number;
  years_to_goal: number; existing_investment?: number;
  inflation_rate?: number; monthly_expense_at_goal?: number; priority?: number;
}

export interface GoalPlan {
  goal_name: string; goal_type: string; future_value: number;
  monthly_sip_required: number; adjusted_sip: number; lumpsum_required: number;
  feasibility: "Feasible" | "Stretch" | "Infeasible";
  feasibility_notes: string[]; // list[str] NOT a single string
  expected_annual_return: number; years_to_goal: number;
}

export interface GoalPlanResponse {
  plans: GoalPlan[]; total_monthly_sip: number;
  sip_as_pct_income: number; feasibility_summary: string;
}

export interface Holding {
  id: number; client_id?: number; scheme_code: number; scheme_name: string;
  units: number; avg_nav: number; invested_amount: number; current_value: number;
  cagr?: number | null; goal_id?: number | null;
}

export interface PortfolioSummary {
  num_holdings: number; total_invested: number; total_current: number;
  absolute_gain: number; gain_percentage: number;
  blended_xirr?: number | null;  // already a % e.g. 12.4
  blended_cagr?: number | null;  // already a % e.g. 10.2
  blended_sharpe?: number | null; // raw ratio e.g. 0.85
}

export interface SectorAllocationItem { sector: string; weight_pct: number; }
export interface SectorAllocationResponse {
  client_id: number; allocations: SectorAllocationItem[]; concentration_warnings: string[];
}

export interface OverlapPair {
  fund_a_code: number; fund_a_name: string;
  fund_b_code: number; fund_b_name: string;
  overlap_pct: number; // already a % e.g. 34.5
  warning_level: "none" | "low" | "medium" | "high";
}
export interface OverlapMatrixResponse {
  client_id: number; pairs: OverlapPair[]; warnings: string[];
}

export interface StockExposureItem {
  isin: string; stock_name: string; sector?: string | null;
  exposure_inr: number; exposure_pct: number; fund_count: number; is_redundant: boolean;
}
export interface StockExposureResponse {
  client_id: number; stocks: StockExposureItem[];
  redundant_flags: string[]; data_gaps: string[];
}

export interface Fund {
  scheme_code: number; scheme_name: string; fund_house: string;
  category: string; sub_category: string; plan_type: string; ai_summary?: string;
}
export interface NavPoint { nav_date: string; nav: number; }

export interface Recommendation {
  goal_name: string; goal_type: GoalType; risk_profile: string;
  horizon_bucket: string; target_sip: number; allocations: CategoryAllocation[];
}
export interface CategoryAllocation { category: string; weight: number; funds: Fund[]; }

export interface Report {
  id: number; client_id: number; report_type: string; period: string;
  file_path: string; approval_status: string; created_at: string; sent_at: string | null;
}

export interface ChatMessage { role: "user" | "assistant"; content: string; timestamp?: string; }
