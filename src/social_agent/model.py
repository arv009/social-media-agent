"""Train, evaluate, explain and use the post-performance model."""
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .features import CATEGORICAL_FEATURES, FEATURES, NUMERIC_FEATURES, TARGET


def time_split(df: pd.DataFrame, test_frac: float = 0.2):
    """Train on older posts, test on the newest ones: the same way the model is used in real life."""
    df = df.sort_values("posted_at")
    cut = int(len(df) * (1 - test_frac))
    return df.iloc[:cut], df.iloc[cut:]


def _preprocessor(scale: bool) -> ColumnTransformer:
    num = StandardScaler() if scale else "passthrough"
    return ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL_FEATURES),
        ("num", num, NUMERIC_FEATURES),
    ])


def candidate_models(seed: int = 42) -> dict:
    return {
        "Ridge (linear)": Pipeline([("prep", _preprocessor(True)), ("model", Ridge(alpha=1.0))]),
        "Random Forest": Pipeline([("prep", _preprocessor(False)),
                                   ("model", RandomForestRegressor(n_estimators=400, min_samples_leaf=3,
                                                                   random_state=seed, n_jobs=-1))]),
        "Gradient Boosting": Pipeline([("prep", _preprocessor(False)),
                                       ("model", HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05,
                                                                               max_leaf_nodes=15, l2_regularization=1.0,
                                                                               random_state=seed))]),
    }


def evaluate(model, test: pd.DataFrame) -> dict:
    pred = model.predict(test[FEATURES])
    y = test[TARGET]
    return {
        "MAE": mean_absolute_error(y, pred),
        "R2": r2_score(y, pred),
        # Ranking quality: does the model put better posts above worse ones? This is what we use it for.
        "Spearman": spearmanr(y, pred).statistic,
    }


def compare_models(train: pd.DataFrame, test: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Fit every candidate plus a 'platform average' baseline and return a results table."""
    results, fitted = {}, {}
    platform_mean = train.groupby("platform")[TARGET].mean()
    base_pred = test["platform"].map(platform_mean).fillna(train[TARGET].mean())
    results["Baseline (platform average)"] = {
        "MAE": mean_absolute_error(test[TARGET], base_pred),
        "R2": r2_score(test[TARGET], base_pred),
        "Spearman": spearmanr(test[TARGET], base_pred).statistic,
    }
    for name, model in candidate_models().items():
        model.fit(train[FEATURES], train[TARGET])
        results[name] = evaluate(model, test)
        fitted[name] = model
    table = pd.DataFrame(results).T.sort_values("MAE")
    return table, fitted


def feature_importance(model, test: pd.DataFrame, n_repeats: int = 20, seed: int = 42) -> pd.Series:
    """Permutation importance: how much worse the model gets when a feature is shuffled."""
    result = permutation_importance(model, test[FEATURES], test[TARGET], n_repeats=n_repeats,
                                    random_state=seed, scoring="neg_mean_absolute_error")
    return pd.Series(result.importances_mean, index=FEATURES).sort_values(ascending=False)


def rank_drafts(model, draft_features: pd.DataFrame) -> pd.DataFrame:
    """Score draft posts and sort best first."""
    out = draft_features.copy()
    out["predicted_engagement_rate"] = model.predict(out[FEATURES])
    return out.sort_values("predicted_engagement_rate", ascending=False)


def best_time_slots(model, draft_row: pd.Series, top_n: int = 5) -> pd.DataFrame:
    """Try the same draft at every weekday/hour and return the best predicted slots."""
    from .features import DAYS, time_of_day
    rows = []
    for d, day in enumerate(DAYS):
        for hour in range(6, 23):
            r = draft_row.copy()
            r["day_of_week"], r["hour"] = day, hour
            r["is_weekend"], r["time_of_day"] = int(d >= 5), time_of_day(hour)
            rows.append(r)
    grid = pd.DataFrame(rows)
    grid["predicted_engagement_rate"] = model.predict(grid[FEATURES])
    return grid.sort_values("predicted_engagement_rate", ascending=False)[
        ["day_of_week", "hour", "predicted_engagement_rate"]].head(top_n)


def save(model, path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)


def load(path):
    return joblib.load(path)


# ---------- Insights for the AI writer ----------

def _lift(df: pd.DataFrame, col: str) -> pd.Series:
    return (df.groupby(col)[TARGET].mean() / df[TARGET].mean() - 1).sort_values(ascending=False)


def generate_insights(df: pd.DataFrame, min_posts: int = 8) -> dict:
    """Plain findings per platform, e.g. 'carousel posts get +35% engagement vs average'.

    Uses simple group averages (easy to explain) on the real data. The model's
    feature importance tells you which of these matter most.
    """
    insights = {}
    for platform, g in df.groupby("platform"):
        if len(g) < min_posts * 2:
            continue
        lines = []
        for col, label in [("media_type", "media"), ("topic", "topic"), ("tone", "tone"),
                           ("time_of_day", "time of day"), ("day_of_week", "day")]:
            counts = g[col].value_counts()
            lift = _lift(g[g[col].isin(counts[counts >= min_posts].index)], col)
            if len(lift) >= 2:
                lines.append(f"Best {label}: {lift.index[0]} ({lift.iloc[0]:+.0%} vs average); "
                             f"worst: {lift.index[-1]} ({lift.iloc[-1]:+.0%}).")
        for col, label in [("has_question", "a question"), ("has_cta", "a call to action"),
                           ("has_link", "a link in the post")]:
            if g[col].nunique() == 2 and g[col].value_counts().min() >= min_posts:
                m = g.groupby(col)[TARGET].mean()
                lines.append(f"Posts with {label}: {m[1] / m[0] - 1:+.0%} engagement vs without.")
        h = g.assign(hashtag_bucket=pd.cut(g["hashtag_count"], [-1, 0, 3, 6, 100],
                                           labels=["0", "1-3", "4-6", "7+"]))
        hb = h.groupby("hashtag_bucket", observed=True)[TARGET].agg(["mean", "size"])
        hb = hb[hb["size"] >= min_posts]
        if len(hb) >= 2:
            lines.append(f"Best hashtag count: {hb['mean'].idxmax()}.")
        insights[platform] = lines
    return insights


def insights_to_prompt(insights: dict) -> str:
    """Format insights as a block to paste into the AI writer's system prompt."""
    out = ["What has worked for this account so far (from past post performance):"]
    for platform, lines in insights.items():
        out.append(f"\n{platform.title()}:")
        out.extend(f"- {line}" for line in lines)
    out.append("\nUse these patterns when writing new posts, but keep the content varied.")
    return "\n".join(out)
