import json
from pathlib import Path

# Chargement du dictionnaire de correspondance directe
with open("mapping.json", "r", encoding="utf-8") as f:
    mapping_data = json.load(f)

# Création du dictionnaire direct alias -> chemin PDF complet
alias_to_pdf_target = {
    item["alias"]: item["pdf_target_path"]
    for item in mapping_data["mappings"]
}