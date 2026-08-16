"""
UFC Fight Predictor - ML Model Training
=========================================
Trains an XGBoost model on historical UFC fights to find
optimal prediction factor weights.

Usage:
  pip install xgboost scikit-learn pandas
  python train_model.py

Reads from your existing CSV files, outputs:
  - Accuracy comparison (current weights vs ML)
  - Feature importance rankings
  - ufc_ml_weights.json (optimized weights for the app)

Place this script in the same folder as your CSV files.
"""

import pandas as pd
import numpy as np
import json
import os
import re
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.metrics import accuracy_score, classification_report
import warnings
warnings.filterwarnings('ignore')

try:
    from xgboost import XGBClassifier
except ImportError:
    print("Install xgboost first: pip install xgboost scikit-learn pandas")
    exit(1)


def parse_height_inches(h):
    """Convert height string like '6\\' 2\"' to inches."""
    if not h or h == '--':
        return None
    m = re.search(r"(\d+)'\s*(\d+)", str(h))
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))
    return None


def parse_reach(r):
    """Convert reach string like '72.0\"' to float."""
    if not r or r == '--':
        return None
    m = re.search(r'([\d.]+)', str(r))
    return float(m.group(1)) if m else None


def parse_weight(w):
    """Convert weight string like '155 lbs.' to float."""
    if not w or w == '--':
        return None
    m = re.search(r'(\d+)', str(w))
    return float(m.group(1)) if m else None


def load_data():
    """Load and merge all CSV files into fighter stats lookup."""
    print("Loading data...")

    # Fighter records (W/L, physical stats)
    records = pd.read_csv('ufc_fighter_records.csv')
    print(f"  Records: {len(records)} fighters")

    # Fighter tott (career performance stats)
    tott = None
    if os.path.exists('ufc_fighter_tott.csv'):
        tott = pd.read_csv('ufc_fighter_tott.csv')
        print(f"  Tott: {len(tott)} fighters")

    # Fight results
    fights = pd.read_csv('ufc_fight_results.csv')
    print(f"  Fights: {len(fights)} results")

    # Build fighter lookup
    fighter_stats = {}

    # From records
    for _, row in records.iterrows():
        name = str(row.get('fighter_name', '')).strip()
        if not name:
            continue
        stats = {
            'name': name,
            'wins': int(row.get('wins', 0) or 0),
            'losses': int(row.get('losses', 0) or 0),
            'draws': int(row.get('draws', 0) or 0),
            'height': parse_height_inches(row.get('height', '')),
            'weight': parse_weight(row.get('weight', '')),
            'reach': parse_reach(row.get('reach', '')),
            'stance': str(row.get('stance', '')).strip(),
        }
        total = stats['wins'] + stats['losses'] + stats['draws']
        stats['win_rate'] = stats['wins'] / total if total > 0 else 0.5
        stats['total_fights'] = total
        fighter_stats[name.lower()] = stats

    # Merge tott stats
    if tott is not None:
        for _, row in tott.iterrows():
            name = str(row.get('FIGHTER', '')).strip().lower()
            if name in fighter_stats:
                for csv_key, stat_key in [('SLPM', 'slpm'), ('STR_ACC', 'str_acc'),
                                           ('SAPM', 'sapm'), ('STR_DEF', 'str_def'),
                                           ('TD_AVG', 'td_avg'), ('TD_ACC', 'td_acc'),
                                           ('TD_DEF', 'td_def'), ('SUB_AVG', 'sub_avg')]:
                    val = row.get(csv_key, None)
                    if pd.notna(val):
                        try:
                            v = float(val)
                            # Convert percentages
                            if stat_key in ('str_acc', 'str_def', 'td_acc', 'td_def') and v > 1:
                                v = v / 100
                            fighter_stats[name][stat_key] = v
                        except (ValueError, TypeError):
                            pass

    print(f"  Total fighters with stats: {len(fighter_stats)}")
    return fighter_stats, fights


def build_training_data(fighter_stats, fights):
    """Build feature matrix from historical fights."""
    print("\nBuilding training dataset...")

    features = []
    labels = []
    fight_info = []

    stance_map = {
        'Orthodox': 0, 'Southpaw': 1, 'Switch': 2, 'Open Stance': 0
    }

    np.random.seed(42)

    for _, fight in fights.iterrows():
        fa_name = str(fight.get('FIGHTER_A', '')).strip().lower()
        fb_name = str(fight.get('FIGHTER_B', '')).strip().lower()
        winner = str(fight.get('WINNER', '')).strip().lower()

        if not fa_name or not fb_name or not winner:
            continue

        fa = fighter_stats.get(fa_name)
        fb = fighter_stats.get(fb_name)

        if not fa or not fb:
            continue

        # Determine actual winner
        if winner == fa_name:
            winner_side = 'A'
        elif winner == fb_name:
            winner_side = 'B'
        else:
            continue

        # Randomly flip A/B to create balanced classes
        # This prevents the model from learning "A always wins"
        flip = np.random.random() > 0.5
        if flip:
            fa, fb = fb, fa
            fa_name, fb_name = fb_name, fa_name
            winner_side = 'B' if winner_side == 'A' else 'A'

        label = 1 if winner_side == 'A' else 0

        # Build feature vector (differences: A - B)
        def safe_diff(key, default=0):
            a_val = fa.get(key, default)
            b_val = fb.get(key, default)
            if a_val is None: a_val = default
            if b_val is None: b_val = default
            return a_val - b_val

        def safe_val(fighter, key, default=0):
            v = fighter.get(key, default)
            return v if v is not None else default

        feat = {
            'slpm_diff': safe_diff('slpm'),
            'sapm_diff': safe_diff('sapm'),
            'str_acc_diff': safe_diff('str_acc'),
            'str_def_diff': safe_diff('str_def'),
            'td_avg_diff': safe_diff('td_avg'),
            'td_acc_diff': safe_diff('td_acc'),
            'td_def_diff': safe_diff('td_def'),
            'sub_avg_diff': safe_diff('sub_avg'),
            'reach_diff': safe_diff('reach'),
            'height_diff': safe_diff('height'),
            'weight_diff': safe_diff('weight'),
            'win_rate_diff': safe_diff('win_rate'),
            'experience_diff': safe_diff('total_fights'),
            'stance_a': stance_map.get(fa.get('stance', ''), 0),
            'stance_b': stance_map.get(fb.get('stance', ''), 0),
            'net_strike_diff': (safe_val(fa, 'slpm') - safe_val(fa, 'sapm')) -
                               (safe_val(fb, 'slpm') - safe_val(fb, 'sapm')),
        }

        features.append(feat)
        labels.append(label)
        fight_info.append(f"{fa.get('name', fa_name)} vs {fb.get('name', fb_name)}")

    X = pd.DataFrame(features)
    y = np.array(labels)

    valid_mask = X.notna().sum(axis=1) >= 8
    X = X[valid_mask].fillna(0)
    y = y[valid_mask.values]
    fight_info = [f for f, v in zip(fight_info, valid_mask) if v]

    print(f"  Training samples: {len(X)}")
    print(f"  Features: {list(X.columns)}")
    print(f"  Class balance: {y.mean():.1%} fighter A wins")

    return X, y, fight_info


def train_and_evaluate(X, y):
    """Train XGBoost model and evaluate accuracy."""
    print("\n" + "="*60)
    print("TRAINING XGBoost MODEL")
    print("="*60)

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # Train XGBoost
    model = XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        eval_metric='logloss',
    )
    model.fit(X_train, y_train)

    # Evaluate
    train_acc = accuracy_score(y_train, model.predict(X_train))
    test_acc = accuracy_score(y_test, model.predict(X_test))

    # Cross-validation
    cv_scores = cross_val_score(model, X, y, cv=5, scoring='accuracy')

    print(f"\n  Training accuracy:  {train_acc:.1%}")
    print(f"  Test accuracy:      {test_acc:.1%}")
    print(f"  Cross-val accuracy: {cv_scores.mean():.1%} (+/- {cv_scores.std():.1%})")

    # Feature importance
    importance = dict(zip(X.columns, model.feature_importances_))
    sorted_imp = sorted(importance.items(), key=lambda x: x[1], reverse=True)

    print(f"\n  Feature Importance (what matters most):")
    print(f"  {'Feature':<25} {'Importance':<15} {'Bar'}")
    print(f"  {'-'*25} {'-'*15} {'-'*30}")
    max_imp = sorted_imp[0][1]
    for feat, imp in sorted_imp:
        bar = '█' * int(30 * imp / max_imp)
        print(f"  {feat:<25} {imp:.4f}         {bar}")

    return model, importance, test_acc, cv_scores.mean()


def generate_weights(model, X, importance):
    """Convert XGBoost model insights into weights for the existing prediction engine."""
    print("\n" + "="*60)
    print("GENERATING OPTIMIZED WEIGHTS")
    print("="*60)

    # Map feature importances to the existing factor names in the app
    factor_mapping = {
        'Win Rate': 'win_rate_diff',
        'Strike Differential': 'net_strike_diff',
        'Strike Accuracy': 'str_acc_diff',
        'Strike Defense': 'str_def_diff',
        'Takedown Game': 'td_avg_diff',
        'Submissions': 'sub_avg_diff',
        'Reach': 'reach_diff',
        'Height': 'height_diff',
        'Experience': 'experience_diff',
        'SLpM': 'slpm_diff',
        'SApM': 'sapm_diff',
        'TD Accuracy': 'td_acc_diff',
        'TD Defense': 'td_def_diff',
    }

    # Normalize importances to create weights (scale 0-5)
    max_imp = max(importance.values())
    weights = {}
    for factor_name, feature_name in factor_mapping.items():
        imp = importance.get(feature_name, 0)
        weight = (imp / max_imp) * 5.0  # Scale to 0-5
        weights[factor_name] = round(weight, 2)

    # Sort by weight
    sorted_weights = sorted(weights.items(), key=lambda x: x[1], reverse=True)

    print(f"\n  Optimized Factor Weights (scale 0-5):")
    print(f"  {'Factor':<25} {'Weight':<10} {'Impact'}")
    print(f"  {'-'*25} {'-'*10} {'-'*20}")
    for name, weight in sorted_weights:
        bar = '█' * int(20 * weight / 5)
        print(f"  {name:<25} {weight:<10.2f} {bar}")

    return weights


def save_weights(weights, test_acc, cv_acc):
    """Save weights to JSON for the app to use."""
    output = {
        'version': '1.0',
        'model': 'XGBoost',
        'test_accuracy': round(float(test_acc), 4),
        'cv_accuracy': round(float(cv_acc), 4),
        'weights': {k: round(float(v), 2) for k, v in weights.items()},
        'note': 'Generated by train_model.py. Plug these into the prediction engine.'
    }

    with open('ufc_ml_weights.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\n  Saved to: ufc_ml_weights.json")
    print(f"  Test accuracy: {test_acc:.1%}")
    print(f"  CV accuracy:   {cv_acc:.1%}")


def print_comparison():
    """Print side-by-side comparison of old vs new weights."""
    print("\n" + "="*60)
    print("CURRENT vs ML-OPTIMIZED WEIGHTS")
    print("="*60)

    current = {
        'Win Rate': 2.0,
        'Strike Differential': 2.5,
        'Strike Accuracy': 1.5,
        'Strike Defense': 1.5,
        'Takedown Game': 3.0,
        'Submissions': 2.0,
        'Reach': 0.6,
        'Height': 0.3,
        'Experience': 0.15,
    }

    if os.path.exists('ufc_ml_weights.json'):
        with open('ufc_ml_weights.json', 'r') as f:
            ml = json.load(f)
        ml_weights = ml['weights']

        print(f"\n  {'Factor':<25} {'Current':<10} {'ML':<10} {'Change'}")
        print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*10}")
        for name, curr in sorted(current.items(), key=lambda x: x[1], reverse=True):
            new = ml_weights.get(name, 0)
            change = new - curr
            arrow = '↑' if change > 0.3 else '↓' if change < -0.3 else '→'
            print(f"  {name:<25} {curr:<10.2f} {new:<10.2f} {arrow} {change:+.2f}")


def main():
    print("="*60)
    print("UFC FIGHT PREDICTOR - ML MODEL TRAINING")
    print("="*60)

    # Check files exist
    required = ['ufc_fighter_records.csv', 'ufc_fight_results.csv']
    for f in required:
        if not os.path.exists(f):
            print(f"ERROR: {f} not found. Run scraper first.")
            return

    # Load data
    fighter_stats, fights = load_data()

    # Build training set
    X, y, fight_info = build_training_data(fighter_stats, fights)

    if len(X) < 100:
        print("ERROR: Not enough training data. Need at least 100 fights.")
        return

    # Train model
    model, importance, test_acc, cv_acc = train_and_evaluate(X, y)

    # Generate weights
    weights = generate_weights(model, X, importance)

    # Save
    save_weights(weights, test_acc, cv_acc)

    # Print comparison
    print_comparison()

    print("\n" + "="*60)
    print("NEXT STEPS:")
    print("  1. Review the weights above")
    print("  2. Share the ufc_ml_weights.json with Claude")
    print("  3. Claude will update the prediction engine with ML weights")
    print("="*60)


if __name__ == "__main__":
    main()
