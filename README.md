# AI Financial Advisory Tool

A full-stack financial advisory tool for Indian mutual fund advisors. Built with Python, Streamlit, and Claude AI.

## Features

- **Client Onboarding** — KYC capture + SEBI-aligned 10-question risk questionnaire
- **Goal-Based Planning** — Inflation-adjusted FV, SIP calculator, multi-goal feasibility check
- **Fund Recommendations** — Allocation matrix by risk profile × time horizon
- **Portfolio Analytics** — XIRR, CAGR, Sharpe ratio, overlap analyser, sector allocator
- **Portfolio Optimiser** — CVXPY max-Sharpe / min-variance with natural-language constraints via Claude
- **Advisory Report** — Streaming Claude narrative, downloadable as Markdown

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| Database | SQLite (local) |
| UI | Streamlit |
| AI | Claude API (`claude-sonnet-4-20250514`) |
| Optimiser | CVXPY + SciPy |
| Scheduler | APScheduler |
| Data sources | mfapi.in (NAV), AMC websites (holdings Excel) |

## Folder Structure

```
financial_advisor/
├── config/         # settings.py — central config, paths, API keys
├── data/           # database.py, client_manager.py — SQLite schema + CRUD
├── engine/         # risk, goal, recommendation, performance, overlap, sector, optimiser
├── fetchers/       # nav_fetcher.py, holdings_fetcher.py
├── ai/             # claude_advisor.py, sector_llm.py
├── ui/             # Streamlit app + 5 pages
│   ├── app.py
│   └── pages/
│       ├── 01_client_onboarding.py
│       ├── 02_goal_planner.py
│       ├── 03_portfolio.py
│       ├── 04_optimiser.py
│       └── 05_advisory_report.py
└── main.py         # CLI demo (Phase 2 end-to-end flow)
```

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/financial-advisor.git
cd financial-advisor
```

### 2. Create a virtual environment

```bash
python3.11 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### 5. Initialise the database

```bash
PYTHONPATH=/path/to/financial_advisor python main.py
```

### 6. Run the Streamlit app

```bash
PYTHONPATH=/path/to/financial_advisor streamlit run ui/app.py
```

## Environment Variables

Create a `.env` file at the project root (never commit this):

```
ANTHROPIC_API_KEY=sk-ant-...
```

See `.env.example` for the full list.

## Status

- [x] Phase 1 — Data foundation
- [x] Phase 2 — Client engine
- [x] Phase 3 — Analytics engine
- [x] Phase 4 — AI + optimiser layer
- [x] Phase 5 — Advisor UI

## License

Private — not for public distribution.
