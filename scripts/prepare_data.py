"""
prepare_data.py — Download and prepare the ESOL (Delaney) solubility dataset.

Output (saved to ../data/):
  - esol.csv            Full dataset: smiles, logS
  - esol_train.csv      80% train split
  - esol_test.csv       20% test split (fixed by random seed)
  - esol_train_20.csv   20% of training data
  - esol_train_50.csv   50% of training data
  - esol_train_80.csv   80% of training data
"""

import os
import sys
import urllib.request
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
RANDOM_SEED = 42

# Multiple fallback URLs for the ESOL dataset
URLS = [
    "https://raw.githubusercontent.com/deepchem/deepchem/master/datasets/delaney-processed.csv",
    "https://raw.githubusercontent.com/dataprofessor/data/master/delaney.csv",
]


def download_esol():
    """Download ESOL dataset from first available URL."""
    for url in URLS:
        try:
            print(f"Trying: {url}")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
            print(f"  Success! ({len(raw)} bytes)")
            return raw
        except Exception as e:
            print(f"  Failed: {e}")
    raise RuntimeError("Could not download ESOL dataset from any source.")


def parse_esol(raw_csv: str) -> pd.DataFrame:
    """Parse raw CSV into a clean DataFrame with columns [smiles, logS]."""
    from io import StringIO
    df = pd.read_csv(StringIO(raw_csv))

    print(f"Raw columns: {list(df.columns)}")
    print(f"Raw shape: {df.shape}")

    # Detect SMILES column (case-insensitive)
    smiles_col = None
    for col in df.columns:
        if "smiles" in col.lower():
            smiles_col = col
            break
    if smiles_col is None:
        raise ValueError(f"Cannot find SMILES column in {list(df.columns)}")

    # Detect logS / solubility column
    target_col = None
    for col in df.columns:
        col_lower = col.lower()
        if "measured" in col_lower and "log" in col_lower:
            target_col = col
            break
    # Fallback: try other common names
    if target_col is None:
        for col in df.columns:
            col_lower = col.lower()
            if "log" in col_lower and ("s" in col_lower or "solub" in col_lower):
                if "esol" not in col_lower:  # avoid ESOL-predicted column
                    target_col = col
                    break

    if target_col is None:
        # Last resort: look for any logS-like column
        raise ValueError(
            f"Cannot find target (logS) column in {list(df.columns)}.\n"
            "First 5 rows:\n" + str(df.head())
        )

    print(f"Using SMILES column: '{smiles_col}'")
    print(f"Using target column: '{target_col}'")

    result = pd.DataFrame({
        "smiles": df[smiles_col].astype(str).str.strip(),
        "logS": pd.to_numeric(df[target_col], errors="coerce"),
    })

    # Drop rows with missing values
    before = len(result)
    result = result.dropna()
    print(f"Dropped {before - len(result)} rows with missing values")

    return result.reset_index(drop=True)


def create_splits(df: pd.DataFrame):
    """Create train/test and data-scale splits."""
    os.makedirs(DATA_DIR, exist_ok=True)

    # Save full dataset
    full_path = os.path.join(DATA_DIR, "esol.csv")
    df.to_csv(full_path, index=False)
    print(f"Saved full dataset: {full_path} ({len(df)} rows)")

    # Fixed train/test split (80/20)
    train_df, test_df = train_test_split(
        df, test_size=0.2, random_state=RANDOM_SEED
    )

    train_path = os.path.join(DATA_DIR, "esol_train.csv")
    test_path = os.path.join(DATA_DIR, "esol_test.csv")
    train_df.to_csv(train_path, index=False)
    test_df.to_csv(test_path, index=False)
    print(f"Saved train: {train_path} ({len(train_df)} rows)")
    print(f"Saved test:  {test_path} ({len(test_df)} rows)")

    # Data-scale subsets (20%, 50%, 80% of training data)
    # Use fixed random seed for reproducibility
    rng = np.random.RandomState(RANDOM_SEED)
    n_train = len(train_df)

    for frac, label in [(0.2, "20"), (0.5, "50"), (0.8, "80")]:
        n = max(10, int(n_train * frac))  # at least 10 samples
        idx = rng.choice(n_train, size=n, replace=False)
        subset = train_df.iloc[idx].reset_index(drop=True)

        out_path = os.path.join(DATA_DIR, f"esol_train_{label}.csv")
        subset.to_csv(out_path, index=False)
        print(f"Saved train_{label}%: {out_path} ({len(subset)} rows)")

    # Also save full training set as 100% reference
    shutil.copy2(train_path, os.path.join(DATA_DIR, "esol_train_100.csv"))
    print(f"Saved train_100%: {os.path.join(DATA_DIR, 'esol_train_100.csv')} ({len(train_df)} rows)")

    # Print summary stats
    print("\n=== Dataset Summary ===")
    print(f"Full dataset: {len(df)} molecules")
    print(f"Training set: {len(train_df)} molecules")
    print(f"Test set:     {len(test_df)} molecules")
    print(f"LogS range:   [{df['logS'].min():.3f}, {df['logS'].max():.3f}]")
    print(f"LogS mean:    {df['logS'].mean():.3f}")
    print(f"LogS std:     {df['logS'].std():.3f}")


if __name__ == "__main__":
    import shutil

    print("=" * 60)
    print("ESOL Dataset Preparation for Chemprop Workshop")
    print("=" * 60)

    raw = download_esol()
    df = parse_esol(raw)
    create_splits(df)

    print("\nDone! Data is ready in:", DATA_DIR)
