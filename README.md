# SWEEP: Season Wins Estimated Above Replacement Player

A WAR-style, era-adjusted value stat for T20 cricket, built from `cricket_data_2026.csv` (IPL player-season batting, bowling and fielding totals, 2008–2025). SWEEP folds batting, bowling and fielding into one number measured in **wins above a replacement-level player**.

A season of 1.0 SWEEP means the player added about one win over what a freely available replacement would have. Stars land around 3 to 4.5 in a season. A 12+ match regular averages about 0.75.

## What's in this folder

| File | What it is |
|---|---|
| `sweep.py` | The model. Reads the raw CSV and writes the two CSVs below. |
| `sweep_player_seasons.csv` | SWEEP for every player-season, split into batting, bowling and fielding. |
| `sweep_career.csv` | Career totals, best season, and SWEEP per 16 matches. |
| `sweep_landscape.html` | Interactive 3D model. Self-contained page built on plain three.js. |
| `SweepLandscape.jsx` | The same 3D model as a React component (React Three Fiber). |
| `README.md` | This file. |

## Run the model

```bash
pip install pandas numpy
mkdir -p out
python3 sweep.py cricket_data_2026.csv out/
```

The script prints the league context it used for each season and the replacement-level gaps, then writes `out/sweep_player_seasons.csv` and `out/sweep_career.csv`.

### Output columns

`sweep_player_seasons.csv`: `Player_Name, Year, Matches_Batted, Runs_Scored, Balls_Faced, Wickets_Taken, Balls_Bowled, Catches_Taken, Stumpings, Bat_SWEEP, Bowl_SWEEP, Field_SWEEP, SWEEP`

`sweep_career.csv`: `Player_Name, Seasons, First, Last, Matches, Runs, Wickets, Bat_SWEEP, Bowl_SWEEP, Field_SWEEP, SWEEP, Best_Season, SWEEP_per_16`

`Bat_SWEEP + Bowl_SWEEP + Field_SWEEP = SWEEP`. `SWEEP_per_16` is a rate stat (SWEEP per 16 matches, about one IPL league stage) so long careers don't automatically beat short ones.

## How it works

For each season the model builds a league context from the data, converts every player's production into runs above a replacement player, then converts runs to wins.

**1. Dismissals.** The file doesn't include them, so they are recovered as `Outs = Runs / Batting_Average`. A player with runs but an average of 0 was never dismissed. With 0 runs and an average of 0, innings are estimated from matches and balls faced.

**2. Era context.** Scoring rose from about 1.2 to 1.55 runs per ball, so every comparison is made against that season's league. Early seasons have only 7 to 12 players, so each season's context is smoothed with its neighbours (weights 0.5, 1, 0.5 for the year before, the year itself and the year after).

**3. Value of a wicket.** `W = 0.35 × league batting average` (about 9 to 11 runs). The same W is used when a batter gets out and when a bowler takes a wicket, so the model is symmetric.

**4. Runs above replacement (RAR).**

```
Bat_RAR   = (Runs − W × Outs)  −  (lg_bat_net_per_ball  − gap_bat)  × Balls_Faced
Bowl_RAR  = (W × Wkts − Runs_Conceded) − (lg_bowl_net_per_ball − gap_bowl) × Balls_Bowled
Field_RAR = 0.40 W × (Catches − 0.85 × expected_catches)  +  0.60 W × Stumpings
```

- Replacement level is the **20th-percentile regular** (100+ balls faced, or 120+ balls bowled, in a season). The gaps come out at about 0.134 (batting) and 0.175 (bowling) net runs per ball below the league average.
- I first tried defining replacement as bench players with very few balls. That was biased: they are on the field briefly because they got out or got hit, which made everyone look far better than they were.
- Seasons with a stumping are treated as wicketkeeping seasons and compared against a keeper-specific catch rate, so keepers don't get free credit for catches.

**5. Runs to wins.** `Runs per win = 11 × 6 × league runs per ball` (about 88 at 8 runs per over, 100+ in 2024 and 2025). `SWEEP = RAR / runs_per_win`.

## Snapshot of results

Top career SWEEP: Virat Kohli 19.1, MS Dhoni 18.0, Sunil Narine 15.3, KL Rahul 14.9, Rashid Khan 12.8.

Top seasons: Kohli 2016 (4.51), Jos Buttler 2022 (3.32), Narine 2024 (3.25), Shubman Gill 2023 (3.03).

## The 3D model

Each player is a pillar standing on a batting-by-bowling floor.

- **East** is Batting SWEEP, **south** is Bowling SWEEP, and **height** is total SWEEP.
- Batters rise along the batting edge, bowlers along the bowling edge, and all-rounders climb the dashed diagonal.
- Colors: orange batter, cyan bowler, purple all-rounder. The glow on each cap shows fielding value.
- Axis ticks are real SWEEP values. Switch between Careers (top 45) and Seasons (top 70), filter with the minimum-SWEEP slider, hover a pillar or click one to pin it, and use the Top 10 list to jump to a player.

### `sweep_landscape.html`

Open it in any modern browser. It loads three.js (pinned to 0.128.0) from jsDelivr and fonts from Google Fonts, so it needs an internet connection the first time. This is also the version that works as a Claude artifact.

### `SweepLandscape.jsx`

For your own React project. It will **not** load as a Claude artifact, because the artifact viewer doesn't support `@react-three/fiber` or `@react-three/drei`. Use the HTML file there.

```bash
npm create vite@latest sweep-viz -- --template react
cd sweep-viz
npm i three @react-three/fiber@8 @react-three/drei@9   # React 18
# React 19: use @react-three/fiber@9 and @react-three/drei@10
cp /path/to/SweepLandscape.jsx src/
```

```jsx
import SweepLandscape from "./SweepLandscape";

export default function App() {
  return <SweepLandscape height={640} />;
}
```

Pass your own data with `<SweepLandscape data={{ career, season }} />`, where each row is `{ n, bat, bowl, field, total, meta }`. The component was syntax-checked but not run in a browser in the environment it was written in, so expect to do a first-run check.

### Refreshing the data in the 3D model

Both 3D files embed a snapshot of the top rows. After re-running `sweep.py`, regenerate the embedded JSON and paste it over the `DEFAULT_DATA` (JSX) or `DATA` (HTML) constant:

```python
import pandas as pd, json
c = pd.read_csv("out/sweep_career.csv"); s = pd.read_csv("out/sweep_player_seasons.csv")
career = [dict(n=r.Player_Name, bat=round(r.Bat_SWEEP, 2), bowl=round(r.Bowl_SWEEP, 2),
               field=round(r.Field_SWEEP, 2), total=round(r.SWEEP, 2),
               meta=f"{int(r.First)}–{int(r.Last)} · {int(r.Matches)} matches") for r in c.head(45).itertuples()]
season = [dict(n=r.Player_Name, bat=round(r.Bat_SWEEP, 2), bowl=round(r.Bowl_SWEEP, 2),
               field=round(r.Field_SWEEP, 2), total=round(r.SWEEP, 2),
               meta=f"{int(r.Year)} · {int(r.Matches_Batted)} matches") for r in s.head(70).itertuples()]
print(json.dumps(dict(career=career, season=season), separators=(",", ":")))
```

## Tuning

These constants sit at the top of `sweep.py`:

| Constant | Default | Effect |
|---|---|---|
| `WICKET_FRAC` | 0.35 | Wicket value as a share of the league batting average. Higher favors bowlers and punishes dismissals more. |
| `RUNS_PER_WIN_K` | 11 | Scales SWEEP up or down. Does not change rankings within a season. |
| `CATCH_FRAC`, `STUMP_FRAC` | 0.40, 0.60 | Fielding value relative to a wicket. |
| `FIELD_REPL` | 0.85 | Replacement fielder's catch rate relative to the league. |
| `QUAL_BALLS_FACED`, `QUAL_BALLS_BOWLED` | 100, 120 | Who counts as a regular when setting replacement level. |
| `REPL_QUANTILE` | 0.20 | Higher moves replacement closer to average, which shrinks everyone's SWEEP. |
| `SMOOTH` | 0.5, 1, 0.5 | How much neighbouring seasons blend into the league context. |

## Caveats

- The file covers about 250 players, not the full league, so league averages and replacement level describe this sample. Rankings are relative to these players.
- Seasons before 2013 rest on very few players, so their league context is noisy even after smoothing.
- The constants above are calibrated by judgment, since there is no ball-by-ball or match-result data to fit them against.
- There is no batting-order or match-situation context. An opener and a finisher with the same totals score the same.
- Dismissals are reconstructed from runs and average, and are approximate for players with an average of 0 and 0 runs.
- Fielding is counted from catches and stumpings only. Run-outs, ground fielding and dropped catches aren't in the data.
