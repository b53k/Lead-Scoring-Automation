import os
import pandas as pd

def ensure_csv_schema(path="data/sample_input.csv"):
    TARGET_COLUMNS = [
    "Name", "Email", "Property Name", "Property Address",
    "City", "State", "Zipcode", "Country"]

    if not os.path.exists(path):
        pd.DataFrame(columns=TARGET_COLUMNS).to_csv(path, index=False)
        return

    df = pd.read_csv(path)

    # Add missing columns for backward compatibility (e.g., old files without Zipcode)
    for col in TARGET_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    # Enforce stable column order and drop unexpected extras
    df = df[TARGET_COLUMNS]
    df.to_csv(path, index=False)