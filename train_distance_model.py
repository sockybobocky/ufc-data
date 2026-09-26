"""
UFC Fight Predictor - Distance Model Training
===============================================
Trains an XGBoost model to predict whether a fight goes to decision
vs being finished early (KO/TKO/Submission).

Uses the same 16 features as the winner model but with a different target:
  1 = fight goes to decision (full distance)
  0 = fight finished early

Usage:
  python train_distance_model.py

Output:
  ufc_ml_distance_model.json (tree model for browser)
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
    if not h or h == '--':
        return None
    m = re.search(r"(\d+)'\s*(\d+)", str(h))
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))
    return None


def parse_reach(r):
    if not r or r == '--':
        return None
    m = re.search(r'([\d.]+)', str(r))
    return float(m.group(1)) if m else None


def parse_weight(w):
    if not w or w == '--':
        return None
    m = re.search(r'(\d+)', str(w))
    return float(m.group(1)) if m else None


def load_data():
    print("Loading data...")
    records = pd.read_csv('ufc_fighter_records.csv')
    print(f"  Records: {len(records)} fighters")

    tott = None
    if os.path.exists('ufc_fighter_tott.csv'):
        tott = pd.read_csv('ufc_fighter_tott.csv')
        print(f"  Tott: {len(tott)} fighters")

    fights = pd.read_csv('ufc_fight_results.csv')
    print(f"  Fights: {len(fights)} results")

    fighter_stats = {}

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
                            if stat_key in ('str_acc', 'str_def', 'td_acc', 'td_def') and v > 1:
                                v = v / 100
                            fighter_stats[name][stat_key] = v
                        except (ValueError, TypeError):
                            pass

    print(f"  Total fighters with stats: {len(fighter_stats)}")
    return fighter_stats, fights


def is_decision(row):
    """Determine if a fight went to decision based on ROUND and TIME."""
    r = int(row['ROUND'])
    t = str(row['TIME']).strip()
    # Decision = fight went full distance (final round ended at 5:00)
    # 3-round fights: R3 at 5:00
    # 5-round fights: R5 at 5:00
    if r == 3 and t == '5:00':
        return 1
    if r == 5 and t == '5:00':
        return 1
    return 0


def build_training_data(fighter_stats, fights):
    """Build feature matrix with distance target."""
    print("\nBuilding training dataset...")

    features = []
    labels = []
    fight_info = []

    stance_map = {
        'Orthodox': 0, 'Southpaw': 1, 'Switch': 2, 'Open Stance': 0
    }

    for _, fight in fights.iterrows():
        fa_name = str(fight.get('FIGHTER_A', '')).strip().lower()
        fb_name = str(fight.get('FIGHTER_B', '')).strip().lower()
        winner = str(fight.get('WINNER', '')).strip().lower()

        # Need ROUND and TIME for the target label
        if pd.isna(fight.get('ROUND')) or pd.isna(fight.get('TIME')):
            continue
        if not fa_name or not fb_name or not winner:
            continue

        fa = fighter_stats.get(fa_name)
        fb = fighter_stats.get(fb_name)
        if not fa or not fb:
            continue

        # Target: did the fight go to decision?
        label = is_decision(fight)

        def safe_diff(key, default=0):
            a_val = fa.get(key, default)
            b_val = fb.get(key, default)
            if a_val is None: a_val = default
            if b_val is None: b_val = default
            return a_val - b_val

        def safe_val(fighter, key, default=0):
            v = fighter.get(key, default)
            return v if v is not None else default

        # For distance prediction, we use COMBINED stats (avg of both fighters)
        # as well as differences. A fight between two heavy hitters is less
        # likely to go to decision than two grapplers.
        feat = {
            # Same difference features as winner model
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
            # NEW combined features for distance prediction
            'slpm_avg': (safe_val(fa, 'slpm') + safe_val(fb, 'slpm')) / 2,
            'sapm_avg': (safe_val(fa, 'sapm') + safe_val(fb, 'sapm')) / 2,
            'str_acc_avg': (safe_val(fa, 'str_acc') + safe_val(fb, 'str_acc')) / 2,
            'str_def_avg': (safe_val(fa, 'str_def') + safe_val(fb, 'str_def')) / 2,
            'td_avg_avg': (safe_val(fa, 'td_avg') + safe_val(fb, 'td_avg')) / 2,
            'sub_avg_avg': (safe_val(fa, 'sub_avg') + safe_val(fb, 'sub_avg')) / 2,
            'experience_avg': (safe_val(fa, 'total_fights') + safe_val(fb, 'total_fights')) / 2,
            'win_rate_avg': (safe_val(fa, 'win_rate', 0.5) + safe_val(fb, 'win_rate', 0.5)) / 2,
            'weight_avg': (safe_val(fa, 'weight') + safe_val(fb, 'weight')) / 2,
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
    print(f"  Features: {len(X.columns)}")
    print(f"  Class balance: {y.mean():.1%} go to decision, {1-y.mean():.1%} finished")

    return X, y, fight_info


def train_and_evaluate(X, y):
    print("\n" + "="*60)
    print("TRAINING DISTANCE MODEL (XGBoost)")
    print("="*60)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

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

    train_acc = accuracy_score(y_train, model.predict(X_train))
    test_acc = accuracy_score(y_test, model.predict(X_test))
    cv_scores = cross_val_score(model, X, y, cv=5, scoring='accuracy')

    print(f"\n  Training accuracy:  {train_acc:.1%}")
    print(f"  Test accuracy:      {test_acc:.1%}")
    print(f"  Cross-val accuracy: {cv_scores.mean():.1%} (+/- {cv_scores.std():.1%})")

    # Feature importance
    importance = dict(zip(X.columns, model.feature_importances_))
    sorted_imp = sorted(importance.items(), key=lambda x: x[1], reverse=True)

    print(f"\n  Feature Importance (what matters most for distance):")
    print(f"  {'Feature':<25} {'Importance':<15}")
    print(f"  {'-'*25} {'-'*15}")
    max_imp = sorted_imp[0][1]
    for feat, imp in sorted_imp:
        bar = '█' * int(30 * imp / max_imp)
        print(f"  {feat:<25} {imp:.4f}         {bar}")

    # Classification report
    print(f"\n  Classification Report:")
    y_pred = model.predict(X_test)
    print(classification_report(y_test, y_pred, target_names=['Finish', 'Decision']))

    return model, importance, test_acc, cv_scores.mean()


def save_model(model, X, test_acc, cv_acc):
    """Export full XGBoost tree model for browser tree-walker."""
    print("\n" + "="*60)
    print("SAVING DISTANCE MODEL")
    print("="*60)

    booster = model.get_booster()
    tree_dump = booster.get_dump(dump_format='json')

    trees = []
    for tree_json in tree_dump:
        trees.append(json.loads(tree_json))

    feature_names = list(X.columns)

    full_model = {
        'version': '1.0',
        'type': 'xgboost_distance',
        'description': 'Predicts probability fight goes to decision vs finish',
        'test_accuracy': round(float(test_acc), 4),
        'cv_accuracy': round(float(cv_acc), 4),
        'n_trees': len(trees),
        'features': feature_names,
        'base_score': 0.5,
        'trees': trees,
    }

    output_file = 'ufc_ml_distance_model.json'
    with open(output_file, 'w') as f:
        json.dump(full_model, f)

    model_size = os.path.getsize(output_file)
    print(f"  Saved to: {output_file} ({model_size:,} bytes, {len(trees)} trees)")
    print(f"  Features: {len(feature_names)}")
    print(f"  Test accuracy: {test_acc:.1%}")
    print(f"  CV accuracy:   {cv_acc:.1%}")

    return output_file


def main():
    print("="*60)
    print("UFC FIGHT PREDICTOR - DISTANCE MODEL TRAINING")
    print("="*60)

    required = ['ufc_fighter_records.csv', 'ufc_fight_results.csv']
    for f in required:
        if not os.path.exists(f):
            print(f"ERROR: {f} not found.")
            return

    fighter_stats, fights = load_data()
    X, y, fight_info = build_training_data(fighter_stats, fights)

    if len(X) < 100:
        print("ERROR: Not enough training data.")
        return

    model, importance, test_acc, cv_acc = train_and_evaluate(X, y)
    output_file = save_model(model, X, test_acc, cv_acc)

    print("\n" + "="*60)
    print("DONE!")
    print(f"  Model saved to: {output_file}")
    print(f"  Ready to integrate into the app")
    print("="*60)


if __name__ == "__main__":
    main()
