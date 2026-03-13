import csv
from collections import defaultdict

def load_patients(filepath=r"C:\Users\10044\OneDrive\Project\pharma_agent\patients.csv"):
    patients = defaultdict(lambda: {"name":"","age":"","phone":"","language":"","drugs":[]})
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [h.strip() for h in reader.fieldnames]
        for row in reader:
            row = {k.strip(): v.strip() for k, v in row.items()}
            pid = row["patient_id"]
            patients[pid]["name"]     = row["name"]
            patients[pid]["age"]      = row["age"]
            patients[pid]["phone"]    = row["phone"]
            patients[pid]["language"] = row["language"]
            patients[pid]["drugs"].append({"drug_name":row["drug_name"],"dosage":row["dosage"],"frequency":row["frequency"],"refill_due":row["refill_due"],"condition":row["condition"],"notes":row["notes"]})
    return dict(patients)

def format_patient_context(patient):
    lines = []
    lines.append("Patient Name : " + patient["name"])
    lines.append("Age          : " + patient["age"])
    lines.append("Language     : " + patient["language"])
    lines.append("Prescriptions:")
    for i, drug in enumerate(patient["drugs"], 1):
        lines.append("  " + str(i) + ". " + drug["drug_name"] + " " + drug["dosage"] + " — " + drug["frequency"] + " | Refill due: " + drug["refill_due"] + " | Condition: " + drug["condition"] + " | Notes: " + drug["notes"])
    return "\n".join(lines)