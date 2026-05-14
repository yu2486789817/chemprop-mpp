"""
molecule_cases.py — Predict solubility for famous molecules and save results.

Used to populate the molecule examples table in demo/PPT.
"""

import os
import sys
import json
import warnings
warnings.filterwarnings("ignore")

import torch
import numpy as np
import pandas as pd
from rdkit import Chem
from rdkit.Chem import Draw, Descriptors, rdMolDescriptors

from chemprop.data import MoleculeDatapoint, MoleculeDataset, build_dataloader
from chemprop.models import MPNN
from chemprop.nn import BondMessagePassing, MeanAggregation, RegressionFFN

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

# Famous molecules
MOLECULES = [
    ("Aspirin",      "CC(=O)Oc1ccccc1C(=O)O",      "C₉H₈O₄",     "Pain reliever / anti-inflammatory"),
    ("Caffeine",     "CN1C=NC2=C1C(=O)N(C(=O)N2C)C", "C₈H₁₀N₄O₂", "Stimulant"),
    ("Benzene",      "c1ccccc1",                     "C₆H₆",       "Simple aromatic — hydrophobic"),
    ("Ibuprofen",    "CC(C)CC1=CC=C(C=C1)C(C)C(=O)O", "C₁₃H₁₈O₂", "NSAID pain reliever"),
    ("Paracetamol",  "CC(=O)NC1=CC=C(C=C1)O",        "C₈H₉NO₂",   "Analgesic / antipyretic"),
    ("Glucose",      "C(C1C(C(C(C(O1)O)O)O)O)O",     "C₆H₁₂O₆",   "Sugar — very hydrophilic"),
    ("Testosterone", "CC12CCC3C(C1CCC2O)CCC4=CC(=O)CCC34C", "C₁₉H₂₈O₂", "Steroid hormone"),
    ("Vitamin C",    "C(C(C1C(=C(C(=O)O1)O)O)O)O",   "C₆H₈O₆",    "Ascorbic acid — antioxidant"),
    ("Tamoxifen",    "CC/C(=C(/c1ccccc1)\\c2ccc(cc2)OCCN(C)C)/c3ccccc3", "C₂₆H₂₉NO", "Breast cancer drug"),
    ("Ampicillin",   "CC1(C(N2C(S1)C(C2=O)NC(=O)C(C3=CC=CC=C3)N)C(=O)O)C", "C₁₆H₁₉N₃O₄S", "Antibiotic"),
]


def build_target_scaler(train_csv):
    """Rebuild the target scaler used during training."""
    train_df = pd.read_csv(train_csv)
    dps = [
        MoleculeDatapoint.from_smi(row["smiles"], y=np.array([row["logS"]], dtype=float))
        for _, row in train_df.iterrows()
    ]
    dataset = MoleculeDataset(dps)
    return dataset.normalize_targets()


def load_model():
    """Find and load the best trained model."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    model_paths = [
        os.path.join(MODELS_DIR, "model_esol_train.pt"),
        os.path.join(MODELS_DIR, "model_esol_train_100.pt"),
    ]

    model_path = None
    for mp in model_paths:
        if os.path.exists(mp):
            model_path = mp
            break

    if model_path is None:
        print("ERROR: No trained model found. Run train.py first.")
        print(f"Searched: {model_paths}")
        sys.exit(1)

    print(f"Loading model: {model_path}")

    checkpoint = torch.load(model_path, map_location=device)
    ckpt_args = checkpoint.get("args", {}) if isinstance(checkpoint, dict) else {}
    hidden_size = int(ckpt_args.get("hidden_size", 300))
    depth = int(ckpt_args.get("depth", 5))
    dropout = float(ckpt_args.get("dropout", 0.1))
    train_csv = ckpt_args.get("train_data", os.path.join(DATA_DIR, "esol_train.csv"))

    mp_block = BondMessagePassing(d_h=hidden_size, depth=depth, dropout=dropout)
    agg = MeanAggregation()
    predictor = RegressionFFN(input_dim=hidden_size, hidden_dim=hidden_size, dropout=dropout)
    model = MPNN(
        message_passing=mp_block,
        agg=agg,
        predictor=predictor,
        batch_norm=True,
    )

    if "model_state" in checkpoint:
        model.load_state_dict(checkpoint["model_state"])
    else:
        model.load_state_dict(checkpoint)

    model.to(device)
    model.eval()
    scaler = build_target_scaler(train_csv)
    return model, device, scaler


def predict(model, device, scaler, smiles):
    """Predict LogS for a single molecule."""
    datapoint = MoleculeDatapoint.from_smi(smiles)
    dataset = MoleculeDataset([datapoint])
    loader = build_dataloader(dataset, batch_size=1, shuffle=False)

    with torch.no_grad():
        for batch in loader:
            bmg = batch.bmg
            bmg.to(device)
            V_d = batch.V_d.to(device) if batch.V_d is not None else None
            X_d = batch.X_d.to(device) if batch.X_d is not None else None
            pred = model(bmg, V_d, X_d).cpu().numpy().reshape(-1, 1)
            return float(scaler.inverse_transform(pred).flatten()[0])


def solubility_label(logS):
    """Return human-readable solubility level."""
    if logS > 0:
        return "High (very soluble)"
    elif logS > -2:
        return "Moderate"
    elif logS > -4:
        return "Low (poorly soluble)"
    else:
        return "Very low (insoluble)"


def main():
    print("=" * 60)
    print("Molecule Case Studies — Solubility Prediction")
    print("=" * 60)

    model, device, scaler = load_model()
    print()

    results = []
    for name, smi, formula, desc in MOLECULES:
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            print(f"  SKIP {name}: invalid SMILES")
            continue

        logS = predict(model, device, scaler, smi)
        level = solubility_label(logS)
        mw = Descriptors.MolWt(mol)
        logP = Descriptors.MolLogP(mol)

        results.append({
            "name": name,
            "smiles": smi,
            "formula": rdMolDescriptors.CalcMolFormula(mol),
            "description": desc,
            "predicted_logS": round(logS, 3),
            "solubility": level,
            "molecular_weight": round(mw, 1),
            "logP": round(logP, 2),
        })

        print(f"  {name:15s}  LogS={logS:+.3f}  {level}  (MW={mw:.0f}, LogP={logP:.2f})")

    # Save
    output_path = os.path.join(RESULTS_DIR, "molecule_cases.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to: {output_path}")

    # Generate molecule images
    print("\nGenerating molecule structure images...")
    mols = [Chem.MolFromSmiles(r["smiles"]) for r in results]
    names = [r["name"] for r in results]
    img = Draw.MolsToGridImage(mols, molsPerRow=5, subImgSize=(250, 180),
                               legends=names)
    img_path = os.path.join(RESULTS_DIR, "molecule_structures.png")
    img.save(img_path)
    print(f"Saved: {img_path}")

    # Print summary table
    df = pd.DataFrame(results)
    df = df[["name", "formula", "predicted_logS", "solubility", "molecular_weight", "logP"]]
    df.columns = ["Molecule", "Formula", "Predicted LogS", "Solubility", "MW", "LogP"]
    print(f"\n{'─'*70}")
    print(df.to_string(index=False))
    print(f"{'─'*70}")


if __name__ == "__main__":
    main()
