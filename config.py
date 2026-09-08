"""
config.py -- central configuration for the CFP ranking app.

The API token defaults to the one previously baked into the project, but you can
override it (recommended) with an environment variable:

    export CFBD_API_KEY=your_key        # macOS / Linux
    set CFBD_API_KEY=your_key           # Windows (cmd)
    $env:CFBD_API_KEY="your_key"        # Windows (PowerShell)
"""

import os

# --- Season -----------------------------------------------------------------
# The season the app ranks. Change once per year.
YEAR = int(os.environ.get("CFP_YEAR", "2026"))

# Seasons of player history pulled to build player-value projections.
HISTORY_YEARS = [YEAR - 3, YEAR - 2, YEAR - 1]

# Recruiting classes pulled to value incoming freshmen.
RECRUIT_YEARS = [YEAR - 2, YEAR - 1, YEAR]

# Regular-season weeks pulled for current-season per-game data (availability).
CURRENT_WEEKS = list(range(1, 16))

# --- CollegeFootballData API ------------------------------------------------
CFBD_BASE_URL = "https://api.collegefootballdata.com"
CFBD_API_KEY = os.environ.get(
    "CFBD_API_KEY",
    "MOFfmt9jd9x5LakTyGcrT3tK1Wfxxdb/zmKB23nz2MI7AZdsNKGNcu5b2VjERc2L",
)

# --- Files / server ---------------------------------------------------------
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RAW_FILE = os.path.join(DATA_DIR, "raw.json")            # last fetched raw data
COMPUTED_FILE = os.path.join(DATA_DIR, "computed.json")  # rankings + team detail
INJURIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "injuries.json")
SCENARIOS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "scenarios.json")           # named what-if worlds

# --- Predictive / Monte Carlo ----------------------------------------------
MC_SIMS = int(os.environ.get("CFP_MC_SIMS", "2000"))     # simulations per run

HOST = os.environ.get("CFP_HOST", "127.0.0.1")
PORT = int(os.environ.get("CFP_PORT", "5000"))

# Only rank FBS teams (others have sparse player data).
FBS_ONLY = True
