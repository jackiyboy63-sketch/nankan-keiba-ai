# NAR AI v3 experimental decision engine

**Research-only. Do not deploy to live betting.** Adds `nar_decision_v3.py` without modifying v1/v2 or existing Actions.

## Snapshot schema (CSV)
`race_id,horse_no,snapshot_at,cutoff_at,score,win_odds,place_odds,source`
All timestamps must include timezone (ISO8601). `snapshot_at` must precede cutoff. Score must be a **pre-race** score from a separately timestamped entry list; NEVER generate it from post-race CSV. Odds must be captured at snapshot time. `place_odds` is a single offered/observed price, not an inferred range. Missing values cause rejection, not interpolation.

## Results schema (CSV, separate file)
`race_id,horse_no,race_date,won,placed,win_return_100,place_return_100`
Labels must be 0/1. Returns in JPY for a 100-yen ticket, 0 for losses. Scratch/refund/dead heat must be preprocessed into explicit status handling **before** running; this prototype currently has no status model and must exclude such races with documented reasons.

## Method
- Score-bin empirical-Bayes calibration for win and place separately, using **strictly earlier calendar dates** and minimum 30 training races (30 is for smoke testing, not a credible calibration sample).
- Bet only when `probability * odds - 1 >= 0.05` (illustrative, NOT optimized or justified). One win/place ticket per race, 100 yen, daily cap 5,000 yen across all races and types. Otherwise skip.
- No quinella/wide probabilities: pairwise joint outcomes cannot be inferred from marginal probabilities alone.
- Freeze selections before joining result/payout rows. Output bets/skips and simple ROI. Does not claim out-of-sample validity without independent timestamped historical snapshots.
- **Known limitation:** for offline historical simulation, snapshot timestamps, pre-race scores, and pre-race odds must be independently archived. Existing `horse_history.csv` is result-derived and **not a valid substitute**. There is no automatic live data collector in this release.
- `race_date` must be the local calendar date corresponding to the race, and snapshots must be ordered/verified by acquisition timestamp. The current prototype checks timestamp ordering against cutoff, but cannot independently verify source authenticity.

## Run
`python -m unittest discover -s tests -v`
`python nar_decision_v3.py --snapshots path/to/prerace_snapshots.csv --results path/to/settled_results.csv --output-dir v3_results`

Do not use the same months to tune and then report final out-of-sample performance. A later untouched period is required. Target ROI >=120% is aspirational, not established.
