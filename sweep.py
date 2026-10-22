"""
SWEEP - Season Wins Estimated Above Replacement Player
A WAR-style, era-adjusted, all-around value metric for T20 cricket
built from player-season batting / bowling / fielding totals.

Usage: python3 sweep.py <input_csv> <out_dir>
"""
import sys
import numpy as np
import pandas as pd

# ----------------------------- tunable constants -----------------------------
WICKET_FRAC = 0.35      # value of a wicket = WICKET_FRAC * league batting average (runs)
RUNS_PER_WIN_K = 11.0   # runs per win = K * league runs-per-over (~88 at 8 rpo)
CATCH_FRAC = 0.40       # a catch is worth 0.40 wickets
STUMP_FRAC = 0.60       # a stumping is worth 0.60 wickets
FIELD_REPL = 0.85       # replacement fielder takes 85% of league-average catches/match
QUAL_BALLS_FACED = 100   # "regular" batter = 100+ balls faced in a season
QUAL_BALLS_BOWLED = 120  # "regular" bowler = 120+ balls (20 overs) bowled in a season
REPL_QUANTILE = 0.20     # replacement level = 20th-percentile regular
SMOOTH = {-1: 0.5, 0: 1.0, 1: 0.5}   # league-context window (years: weight)


def load(path):
    raw = pd.read_csv(path, dtype=str)
    df = raw[raw["Year"] != "No stats"].copy()
    skip = {"Player_Name", "Best_Bowling_Match", "Highest_Score"}
    for c in df.columns:
        if c not in skip:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["Year"] = df["Year"].astype(int)
    # a duplicate player-season would double count; keep the larger workload row
    df["_load"] = df["Balls_Faced"] + df["Balls_Bowled"]
    df = (df.sort_values("_load", ascending=False)
            .drop_duplicates(["Player_Name", "Year"]).drop(columns="_load"))
    return df.reset_index(drop=True)


def add_outs(df):
    """Dismissals are not in the file; recover them from runs / average."""
    outs = np.where(df.Batting_Average > 0, df.Runs_Scored / df.Batting_Average, np.nan)
    # average == 0 with runs > 0 -> never dismissed
    outs = np.where((df.Batting_Average == 0) & (df.Runs_Scored > 0), 0.0, outs)
    # average == 0 and 0 runs -> ambiguous; estimate innings from balls/matches
    inn_est = np.minimum(df.Matches_Batted, df.Balls_Faced)
    outs = np.where(np.isnan(outs), np.maximum(0.0, inn_est - df.Not_Outs), outs)
    df["Outs"] = outs
    return df


def league_context(df):
    g = df.groupby("Year").agg(
        runs=("Runs_Scored", "sum"), bf=("Balls_Faced", "sum"), outs=("Outs", "sum"),
        rc=("Runs_Conceded", "sum"), bb=("Balls_Bowled", "sum"), wk=("Wickets_Taken", "sum"),
        ct=("Catches_Taken", "sum"), m=("Matches_Batted", "sum"))
    years = g.index.values
    rows = {}
    for y in years:
        w_tot = {k: 0.0 for k in g.columns}
        for off, w in SMOOTH.items():
            if y + off in g.index:
                for k in g.columns:
                    w_tot[k] += w * g.loc[y + off, k]
        rows[y] = w_tot
    s = pd.DataFrame(rows).T
    ctx = pd.DataFrame(index=s.index)
    ctx["lg_rpb"] = s.runs / s.bf
    ctx["lg_avg"] = s.runs / s.outs
    ctx["W"] = WICKET_FRAC * ctx.lg_avg
    ctx["lg_cpm"] = s.ct / s.m
    ctx["rpw"] = RUNS_PER_WIN_K * 6 * ctx.lg_rpb
    # league per-ball net values
    ctx["lg_bat_nr_pb"] = (s.runs - ctx.W * s.outs) / s.bf
    ctx["lg_bowl_nrs_pb"] = (ctx.W * s.wk - s.rc) / s.bb
    return ctx


def replacement_gaps(df, ctx):
    """Replacement level = how far (per ball) the 20th-percentile regular sits below
    the era's league average. Using regulars (not bench players) avoids the bias that
    bench players are on the field briefly *because* they got out / got hit."""
    d = df.join(ctx[["W", "lg_bat_nr_pb", "lg_bowl_nrs_pb"]], on="Year")
    b = d[d.Balls_Faced >= QUAL_BALLS_FACED]
    bat_dev = (b.Runs_Scored - b.W * b.Outs) / b.Balls_Faced - b.lg_bat_nr_pb
    p = d[d.Balls_Bowled >= QUAL_BALLS_BOWLED]
    bowl_dev = (p.W * p.Wickets_Taken - p.Runs_Conceded) / p.Balls_Bowled - p.lg_bowl_nrs_pb
    return -bat_dev.quantile(REPL_QUANTILE), -bowl_dev.quantile(REPL_QUANTILE)


def compute(df):
    df = add_outs(df)
    ctx = league_context(df)
    bat_gap, bowl_gap = replacement_gaps(df, ctx)
    d = df.join(ctx, on="Year")

    # batting: net runs (runs minus the cost of getting out) vs a replacement bat
    d["Bat_NetRuns"] = d.Runs_Scored - d.W * d.Outs
    d["Bat_RAR"] = d.Bat_NetRuns - (d.lg_bat_nr_pb - bat_gap) * d.Balls_Faced

    # bowling: runs saved + wicket value vs a replacement bowler
    d["Bowl_NetRuns"] = d.W * d.Wickets_Taken - d.Runs_Conceded
    d["Bowl_RAR"] = d.Bowl_NetRuns - (d.lg_bowl_nrs_pb - bowl_gap) * d.Balls_Bowled

    # fielding / keeping
    # keepers (seasons with a stumping) take far more catches than outfielders, so they
    # are benchmarked against a keeper-specific catch rate (pooled multiplier vs. others)
    keeper = d.Stumpings > 0
    k_cpm = d[keeper].Catches_Taken.sum() / d[keeper].Matches_Batted.sum()
    o_cpm = d[~keeper].Catches_Taken.sum() / d[~keeper].Matches_Batted.sum()
    mult = np.where(keeper, k_cpm / o_cpm, 1.0)
    d["Is_Keeper"] = keeper
    exp_catches = FIELD_REPL * d.lg_cpm * mult * d.Matches_Batted
    d["Field_RAR"] = (CATCH_FRAC * d.W * (d.Catches_Taken - exp_catches)
                      + STUMP_FRAC * d.W * d.Stumpings)

    d["RAR"] = d.Bat_RAR + d.Bowl_RAR + d.Field_RAR
    for k in ("Bat", "Bowl", "Field"):
        d[f"{k}_SWEEP"] = d[f"{k}_RAR"] / d.rpw
    d["SWEEP"] = d.RAR / d.rpw
    return d, ctx, bat_gap, bowl_gap


def main(path, out):
    df = load(path)
    d, ctx, bg, pg = compute(df)
    print(f"replacement gap: bat {bg:.3f} net runs/ball, bowl {pg:.3f} net runs/ball")
    print(ctx.round(3).to_string())

    cols = ["Player_Name", "Year", "Matches_Batted", "Runs_Scored", "Balls_Faced",
            "Wickets_Taken", "Balls_Bowled", "Catches_Taken", "Stumpings",
            "Bat_SWEEP", "Bowl_SWEEP", "Field_SWEEP", "SWEEP"]
    season = d[cols].sort_values("SWEEP", ascending=False).round(2)
    season.to_csv(f"{out}/sweep_player_seasons.csv", index=False)

    car = d.groupby("Player_Name").agg(
        Seasons=("Year", "nunique"), First=("Year", "min"), Last=("Year", "max"),
        Matches=("Matches_Batted", "sum"), Runs=("Runs_Scored", "sum"),
        Wickets=("Wickets_Taken", "sum"),
        Bat_SWEEP=("Bat_SWEEP", "sum"), Bowl_SWEEP=("Bowl_SWEEP", "sum"),
        Field_SWEEP=("Field_SWEEP", "sum"), SWEEP=("SWEEP", "sum"),
        Best_Season=("SWEEP", "max")).reset_index()
    car["SWEEP_per_16"] = car.SWEEP / car.Matches * 16   # ~one IPL league stage
    car = car.sort_values("SWEEP", ascending=False).round(2)
    car.to_csv(f"{out}/sweep_career.csv", index=False)
    return d, season, car


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
