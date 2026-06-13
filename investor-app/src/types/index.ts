/**
 * types/index.ts — All TypeScript types mirroring FastAPI schemas
 */
export interface OtpRequestPayload  { email: string; phone?: string }
export interface OtpVerifyPayload   { email: string; otp: string }
export interface AuthTokens         { access_token: string; refresh_token: string; token_type: string }

export interface Client {
  id: number; name: string; email: string; phone: string; age: number;
  annual_income: number; monthly_income: number; dependants: number; pan: string;
  risk_profile: string | null; risk_score: number | null;
  onboarding_status: string; advisor_id: number | null;
}

export type GoalType = "retirement" | "education" | "house" | "emergency" | "wedding" | "travel" | "custom";

export interface Goal {
  id: number; client_id: number; goal_name: string; goal_type: GoalType;
  target_amount: number; target_year: number; current_savings: number;
  monthly_sip: number; priority: number; feasibility?: string;
}

export interface GoalPlanRequest {
  goal_type: GoalType; name: string; target_amount_today: number;
  years_to_goal: number; existing_investment?: number;
  inflation_rate?: number; monthly_expense_at_goal?: number;
}

export interface GoalPlan {
  goal_name: string; goal_type: GoalType; future_value: number;
  monthly_sip_required: number; adjusted_sip: number; lumpsum_required: number;
  feasibility: "Feasible" | "Stretch" | "Infeasible"; feasibility_notes: string;
  expected_annual_return: number;
}

export interface Holding {
  id: number; scheme_code: number; scheme_name: string;
  units: number; avg_nav: number; invested_amount: number;
  current_value: number; cagr?: number; xirr?: number;
}

export interface PortfolioSummary {
  num_holdings: number; total_invested: number; total_current: number;
  absolute_gain: number; gain_percentage: number;
  blended_xirr?: number; sharpe_ratio?: number;
}

export interface SectorAllocation { sector: string; weight: number; }

export interface OverlapResult {
  stock_exposures: StockExposure[]; sector_exposures: SectorExposure[];
  redundant_stocks: string[]; narrative?: string;
}
export interface StockExposure {
  stock_name: string; isin: string; exposure_inr: number; exposure_pct: number; num_funds: number;
}
export interface SectorExposure { sector: string; exposure_inr: number; exposure_pct: number; }

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
  id: number; client_id: number; advisor_id: number; report_type: string;
  period: string; file_path: string; approval_status: string;
  created_at: string; sent_at: string | null;
}

export interface ChatMessage { role: "user" | "assistant"; content: string; timestamp?: string; }
