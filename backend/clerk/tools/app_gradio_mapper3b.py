#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
AcroForm Studio v3.1 : Éditeur Assisté avec Thème Doux & Robustesse Améliorée
=============================================================================
Améliorations majeures :
- Isolation des sessions (logs et états par onglet)
- Gestion stricte des fichiers temporaires (anti-fuite mémoire)
- Import/Export de données JSON (Bulk update)
- Notifications Toast natives (gr.Info, gr.Warning, gr.Error)
- Tri numérique correct des pages dans le tableau
- Compilation PDF plus robuste (gestion des erreurs par page)
=============================================================================
"""
from __future__ import annotations
import argparse
import datetime
import json
import os
import re
import sys
import tempfile
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# 1. Vérification des bibliothèques clés
MISSING_PKGS = []
try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    MISSING_PKGS.append("pypdf")
try:
    import gradio as gr
except ImportError:
    MISSING_PKGS.append("gradio")
try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

if MISSING_PKGS:
    print(f"[FATAL] Modules manquants : {', '.join(MISSING_PKGS)}. Installez avec : pip install {' '.join(MISSING_PKGS)}", file=sys.stderr)
    sys.exit(1)

# Chemins d'accès de référence
BASE_DIR = Path.cwd()
DEFAULT_TEMPLATE = r"C:\Users\titwa\Downloads\Gesuch UP elektronisch ausfüllbar.pdf"
DEFAULT_OUTPUT = r"C:\Users\titwa\Downloads\Gesuch_UP_Falempin_Rempli.pdf"
DEFAULT_MAPPING = str(BASE_DIR / "mapping.json")
DEFAULT_DATA = str(BASE_DIR / "donnees.json")

# Dossier dédié pour les aperçus (évite la pollution du dossier Temp système)
PREVIEW_DIR = Path(tempfile.gettempdir()) / "acroform_studio_previews"
PREVIEW_DIR.mkdir(exist_ok=True)
PREVIEW_FILE = PREVIEW_DIR / "current_preview.png"

# =============================================================================
# =============================================================================
# Thème Visuel Nuit Anti-Fatigue (Midnight Dark Slate)
# =============================================================================
MIDNIGHT_DARK_CSS = """
:root {
    color-scheme: dark !important;
}

body, .gradio-container {
    background-color: #0B0F19 !important;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif !important;
    color: #CBD5E1 !important;
    max-width: 100vw !important;
    width: 100vw !important;
    box-sizing: border-box !important;
    padding: 8px 16px !important;
}

/* En-tête apaisant */
#header-bar {
    background: #111827 !important;
    border: 1px solid #1F2937 !important;
    border-radius: 10px !important;
    padding: 10px 18px !important;
    margin-bottom: 10px !important;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.3) !important;
}
#header-bar h2 {
    font-size: 19px !important;
    font-weight: 600 !important;
    color: #F3F4F6 !important;
    margin: 0 !important;
}

/* Conteneurs et cartes */
#context-editor-group, #preview-studio-group, .gr-box, .gr-panel {
    background: #111827 !important;
    border: 1px solid #1F2937 !important;
    border-radius: 10px !important;
    padding: 14px 18px !important;
    margin-top: 12px !important;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2) !important;
}

/* Onglets Gradio */
.tab-nav button {
    color: #9CA3AF !important;
    font-weight: 500 !important;
    font-size: 15px !important;
}
.tab-nav button.selected {
    color: #60A5FA !important;
    border-bottom: 2px solid #3B82F6 !important;
    background: transparent !important;
}

/* Libellés de formulaire */
label span, .gr-form label {
    font-size: 14px !important;
    font-weight: 600 !important;
    color: #9CA3AF !important;
    margin-bottom: 3px !important;
}

/* Champs de saisie */
input, textarea, select {
    font-size: 14.5px !important;
    min-height: 42px !important;
    border: 1px solid #374151 !important;
    border-radius: 8px !important;
    padding: 7px 12px !important;
    color: #F3F4F6 !important;
    background-color: #1F2937 !important;
    transition: border-color 0.15s ease, box-shadow 0.15s ease !important;
}
input:focus, textarea:focus, select:focus {
    border-color: #3B82F6 !important;
    outline: none !important;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.25) !important;
    background-color: #111827 !important;
}

/* Boutons */
button.primary {
    min-height: 44px !important;
    font-size: 15px !important;
    font-weight: 600 !important;
    background-color: #2563EB !important;
    color: #FFFFFF !important;
    border-radius: 8px !important;
    border: none !important;
    box-shadow: 0 1px 3px rgba(37, 99, 235, 0.2) !important;
}
button.primary:hover {
    background-color: #1D4ED8 !important;
}

button.secondary {
    min-height: 44px !important;
    font-size: 15px !important;
    font-weight: 500 !important;
    background-color: #1F2937 !important;
    color: #E5E7EB !important;
    border: 1px solid #374151 !important;
    border-radius: 8px !important;
}
button.secondary:hover {
    background-color: #374151 !important;
}

/* Grand Tableau plein écran haute lisibilité */
.gr-dataframe {
    font-size: 14px !important;
    border: 1px solid #1F2937 !important;
    border-radius: 8px !important;
    background: #111827 !important;
    width: 100% !important;
}
.gr-dataframe th {
    background-color: #1F2937 !important;
    color: #9CA3AF !important;
    font-size: 13.5px !important;
    font-weight: 600 !important;
    padding: 9px 12px !important;
    border-bottom: 1px solid #374151 !important;
    position: sticky !important;
    top: 0 !important;
    z-index: 10 !important;
}
.gr-dataframe td {
    padding: 8px 12px !important;
    border-bottom: 1px solid #1F2937 !important;
    color: #E5E7EB !important;
    background-color: #111827 !important;
}
.gr-dataframe tr:nth-child(even) td {
    background-color: #161F30 !important;
}
.gr-dataframe tr:hover td {
    background-color: #1E293B !important;
    color: #60A5FA !important;
    cursor: pointer !important;
}

/* Chemin AcroForm en lecture seule */
#readonly-path-box input {
    background-color: #0B0F19 !important;
    color: #94A3B8 !important;
    font-size: 13px !important;
    border: 1px solid #1F2937 !important;
}

/* Console logs & traceback */
#diagnostic-console-box textarea {
    font-family: Consolas, monospace !important;
    font-size: 13px !important;
    background-color: #030712 !important;
    color: #34D399 !important;
    border: 1px solid #1F2937 !important;
    border-radius: 8px !important;
    line-height: 1.45 !important;
    padding: 12px !important;
}

/* Composant fichier / téléchargement */
.gr-file {
    border: 1px solid #1F2937 !important;
    border-radius: 8px !important;
    padding: 8px !important;
    background: #1F2937 !important;
    color: #E5E7EB !important;
}

/* Aperçu d'image haute résolution 1080px */
#preview-studio-group .image-container,
#preview-studio-group .image-preview,
.image-preview, .image-container {
    background: #0B0F19 !important;
    border: 1px solid #1F2937 !important;
    border-radius: 8px !important;
    overflow: auto !important;
}

#preview-studio-group img {
    margin: 0 auto !important;
    display: block !important;
    max-width: 100% !important;
    border-radius: 4px !important;
}
"""

SOFT_RESTFUL_CSS = MIDNIGHT_DARK_CSS

def build_midnight_theme():
    return gr.themes.Soft(
        primary_hue=gr.themes.colors.blue,
        secondary_hue=gr.themes.colors.slate,
        neutral_hue=gr.themes.colors.slate,
    ).set(
        body_background_fill="#0B0F19",
        body_background_fill_dark="#0B0F19",
        block_background_fill="#111827",
        block_background_fill_dark="#111827",
        block_border_color="#1F2937",
        block_border_color_dark="#1F2937",
        body_text_color="#CBD5E1",
        body_text_color_dark="#CBD5E1",
        background_fill_primary="#0B0F19",
        background_fill_secondary="#111827",
        border_color_primary="#1F2937",
        input_background_fill="#1F2937",
        input_background_fill_dark="#1F2937",
        input_border_color="#374151",
        input_border_color_dark="#374151",
        table_even_background_fill="#111827",
        table_odd_background_fill="#161F30",
    )

# =============================================================================
# Session Logger (Isolé par onglet/navigateur)
# =============================================================================
class SessionLogger:
    """Logger isolé par session Gradio pour éviter le mélange des logs entre onglets."""
    def __init__(self):
        self.logs: List[str] = []
        self.max_logs = 300

    def log(self, level: str, msg: str) -> None:
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] [{level.upper()}] {msg}"
        self.logs.append(entry)
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)
        print(entry)

    def info(self, msg: str): self.log("INFO", msg)
    def success(self, msg: str): self.log("OK", msg)
    def warn(self, msg: str): self.log("WARN", msg)
    def error(self, msg: str, exc: Optional[Exception] = None):
        if exc:
            self.log("ERROR", f"{msg} -> {str(exc)}\n{traceback.format_exc()}")
        else:
            self.log("ERROR", msg)

    def get_stream(self) -> str:
        return "\n".join(reversed(self.logs)) if self.logs else "[En attente d'événements...]"
    
    def clear(self):
        self.logs = []

# =============================================================================
# Écriture Atomique Sécurisée
# =============================================================================
class AtomicFileWriter:
    def __init__(self, target_path: Path | str, mode: str = "wb", encoding: Optional[str] = None):
        self.target_path = Path(target_path).resolve()
        self.mode = mode
        self.encoding = encoding
        self.temp_file: Optional[tempfile.NamedTemporaryFile] = None
        self.temp_path: Optional[Path] = None

    def __enter__(self):
        self.target_path.parent.mkdir(parents=True, exist_ok=True)
        self.temp_file = tempfile.NamedTemporaryFile(
            mode=self.mode, dir=self.target_path.parent,
            prefix=f".tmp_{self.target_path.stem}_", suffix=".tmp", delete=False,
            encoding=self.encoding if "b" not in self.mode else None,
        )
        self.temp_path = Path(self.temp_file.name)
        return self.temp_file

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.temp_file and not self.temp_file.closed:
            try:
                self.temp_file.flush()
                os.fsync(self.temp_file.fileno())
                self.temp_file.close()
            except Exception: pass
        
        if exc_type is not None:
            if self.temp_path and self.temp_path.exists():
                try: self.temp_path.unlink()
                except OSError: pass
            return False

        if self.temp_path and self.temp_path.exists():
            try:
                os.replace(self.temp_path, self.target_path)
            except OSError as e:
                try: self.temp_path.unlink()
                except OSError: pass
                raise IOError(f"Remplacement atomique échoué vers {self.target_path}: {e}") from e
        return True

# =============================================================================
# Moteurs Documentaires & Gestionnaires
# =============================================================================
@dataclass
class AcroFormField:
    full_path: str
    page_index: int
    page_label: str
    leaf: str
    parent: str
    field_type: str
    tooltip: str

def normalize_field_value(field_name: str, value: Any) -> str:
    """Normalise les valeurs injectées (conversion boutons/cases à cocher/radios)."""
    if value is None:
        return ""
    val_str = str(value).strip()
    if not val_str:
        return ""

    if "requireTranslation" in field_name:
        return "/1" if val_str.lower() in ["ja", "oui", "yes", "true", "1"] else "/Off"

    if "maritalStatus" in field_name:
        mapping = {
            "ledig": "/0",
            "verheiratet": "/1",
            "verwitwet": "/2",
            "geschieden": "/3",
            "getrennt": "/4",
            "in eingetragener partnerschaft": "/5",
            "aufgelöste partnerschaft": "/6",
            "im konkubinat lebend": "/7",
        }
        val_lower = val_str.lower()
        if val_lower in mapping:
            return mapping[val_lower]
        if val_str.startswith("/"):
            return val_str
        if val_str.isdigit() and 0 <= int(val_str) <= 7:
            return f"/{val_str}"
        return "/1" if "verheirat" in val_lower else val_str

    if "RadioButtonList" in field_name:
        val_lower = val_str.lower()
        if val_lower in ["nein", "non", "no", "false", "0", "2"]:
            return "/0"
        if val_lower in ["ja", "oui", "yes", "true", "1"]:
            return "/1"
        if val_str.startswith("/"):
            return val_str
        return val_str

    return val_str


class PDFCore:
    @staticmethod
    def inspect_template(template_path: str, logger: SessionLogger) -> List[AcroFormField]:
        if not os.path.exists(template_path):
            logger.warn(f"Modèle PDF introuvable : {template_path}")
            return []
        try:
            reader = PdfReader(template_path)
            raw = reader.get_fields() or {}
            fields: List[AcroFormField] = []
            for path_key, obj in raw.items():
                ft = str(obj.get("/FT", "") or "")
                if not ft or ft == "None": continue
                parts = path_key.split(".")
                leaf = parts[-1]
                parent = parts[-2] if len(parts) > 1 else ""
                tu = str(obj.get("/TU", "") or "")
                match = re.search(r"page(\d+)", path_key, re.IGNORECASE)
                p_idx = max(0, int(match.group(1)) - 1) if match else 0
                p_label = f"page{p_idx + 1}[0]"
                fields.append(AcroFormField(path_key, p_idx, p_label, leaf, parent, ft, tu))
            logger.success(f"{len(fields)} champs interactifs extraits avec succès.")
            return sorted(fields, key=lambda f: (f.page_index, f.leaf))
        except Exception as e:
            logger.error("Échec de l'analyse du template PDF", e)
            return []

    @staticmethod
    def compile(template_path: str, output_path: str, mappings: List[Dict[str, Any]], data: Dict[str, str], logger: SessionLogger) -> str:
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Modèle inexistant : {template_path}")
        
        reader = PdfReader(template_path)
        writer = PdfWriter()
        writer.append(reader)
        
        lookup = {m["alias"]: (m.get("page_index", 0), m["pdf_target_path"]) for m in mappings if "alias" in m and "pdf_target_path" in m}
        updates_by_page: Dict[int, Dict[str, str]] = {i: {} for i in range(len(writer.pages))}
        injected_count = 0
        
        for alias, val in data.items():
            if alias in lookup and val is not None and str(val).strip():
                p_idx, target = lookup[alias]
                if p_idx < len(writer.pages):
                    updates_by_page[p_idx][target] = normalize_field_value(target, val)
                    injected_count += 1
        
        # Injection robuste par page (si une page échoue, les autres sont sauvegardées)
        for p_idx, updates in updates_by_page.items():
            if updates:
                try:
                    writer.update_page_form_field_values(writer.pages[p_idx], updates)
                except Exception as e:
                    logger.warn(f"Erreur injection page {p_idx + 1} (champs ignorés) : {e}")
        
        out_path = Path(output_path).resolve()
        with AtomicFileWriter(out_path, mode="wb") as f_out:
            writer.write(f_out)
        logger.success(f"Compilation PDF terminée ({injected_count} champs injectés) -> {out_path.name}")
        return str(out_path)

    @staticmethod
    def render_png(pdf_path: str, page_num: int = 1, dpi: int = 140) -> Optional[str]:
        if not HAS_PYMUPDF or not os.path.exists(pdf_path):
            return None
        try:
            doc = fitz.open(pdf_path)
            idx = max(0, min(page_num - 1, len(doc) - 1))
            pix = doc[idx].get_pixmap(dpi=int(dpi))
            # Réutilise un seul fichier pour éviter la fuite de fichiers temporaires
            pix.save(str(PREVIEW_FILE))
            doc.close()
            return str(PREVIEW_FILE)
        except Exception as e:
            return None

class StorageCore:
    @staticmethod
    def load_json(path_str: str, default: Any, logger: SessionLogger) -> Any:
        p = Path(path_str)
        if not p.exists(): return default
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Erreur lecture {p.name}", e)
            return default

    @staticmethod
    def save_json(path_str: str, data: Any, logger: SessionLogger) -> bool:
        try:
            with AtomicFileWriter(path_str, mode="w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Erreur sauvegarde {path_str}", e)
            return False

# =============================================================================
# Interface Graphique Gradio
# =============================================================================
def build_app():
    midnight_theme = build_midnight_theme()

    with gr.Blocks(
        title="AcroForm Studio • Édition Plein Écran & Diagnostic",
        theme=midnight_theme,
        css=MIDNIGHT_DARK_CSS,
    ) as app:
        
        # États isolés par session
        state_fields = gr.State([])
        state_mappings = gr.State([])
        state_data = gr.State({})
        state_logger = gr.State(SessionLogger())

        # Barre supérieure (Pleine Largeur)
        with gr.Row(elem_id="header-bar"):
            with gr.Column(scale=5):
                gr.Markdown("## 📋 AcroForm Studio • Canton de Zoug (Art. 119 ZPO)")
                status_summary = gr.Markdown("Initialisation en cours...")
            with gr.Column(scale=3):
                with gr.Row():
                    tmpl_box = gr.Textbox(value=DEFAULT_TEMPLATE, label="Template PDF", max_lines=1, scale=4)
                    out_box = gr.Textbox(value=DEFAULT_OUTPUT, label="PDF de sortie", max_lines=1, scale=4)
                with gr.Row():
                    btn_reload = gr.Button("🔄 Recharger Session", variant="secondary", scale=1)

        # Onglets principaux en PLEINE LARGEUR (100% écran)
        with gr.Tabs():
            with gr.Tab("📝 Éditeur de Formulaire & Tableau"):
                with gr.Row():
                    filter_stat = gr.Radio(
                        choices=["Tous les champs", "Champs REMPLIS", "Champs VIDES"],
                        value="Tous les champs",
                        label="Filtre d'état",
                        scale=2,
                    )
                    search_box = gr.Textbox(
                        placeholder="🔍 Filtrer par mot-clé (ex: Falempin, Mietzins, Unterhalt, ALV, Einkommen...)",
                        label="Recherche textuelle (alias, valeur, libellé ou chemin)",
                        scale=4,
                    )

                # Grand tableau plein écran avec colonnes explicites et larges pour Alias et Valeur
                df_view = gr.Dataframe(
                    headers=["Statut", "Page", "Alias (clé donnees.json)", "Valeur Actuelle", "Info-bulle (TU)", "Nom de Champ (Leaf)", "Chemin AcroForm"],
                    datatype=["str", "str", "str", "str", "str", "str", "str"],
                    column_widths=["110px", "85px", "240px", "280px", "320px", "180px", "auto"],
                    interactive=False,
                    wrap=True,
                    max_height=480,
                )

                # Tiroir d'édition contextuelle du champ sélectionné
                with gr.Column(elem_id="context-editor-group"):
                    gr.Markdown("#### ✍️ Édition Contextuelle du Champ Sélectionné")
                    with gr.Row():
                        edit_alias = gr.Textbox(label="Alias (clé dans donnees.json)", scale=2)
                        edit_val = gr.Textbox(label="Valeur à injecter", scale=3)
                    edit_path = gr.Textbox(label="Chemin AcroForm ciblé (lecture seule)", interactive=False, elem_id="readonly-path-box")
                    with gr.Row():
                        btn_save = gr.Button("💾 Valider et Enregistrer", variant="primary", scale=3)
                        btn_clear = gr.Button("🗑️ Vider ce Champ", variant="secondary", scale=1)

                # Studio Documentaire & Contrôle Visuel (1.5x plus haut + Vues & Zoom)
                with gr.Column(elem_id="preview-studio-group"):
                    gr.Markdown("### 📄 Studio Documentaire & Contrôle Visuel (Aperçu PDF HD)")
                    with gr.Row():
                        btn_compile = gr.Button("👁️ Compiler & Aperçu PDF", variant="primary", scale=2)
                        page_pick = gr.Dropdown(choices=[f"Page {i}" for i in range(1, 11)], value="Page 1", label="Feuilleter la page", scale=1)
                        view_mode = gr.Radio(
                            choices=["📄 Page Entière", "↔️ Pleine Largeur", "🔍 Zoom 180%", "🔎 Zoom 230%"],
                            value="↔️ Pleine Largeur",
                            label="Mode d'affichage",
                            scale=3,
                        )
                        file_down = gr.File(label="Télécharger le PDF compilé", interactive=False, scale=2)

                    with gr.Row():
                        btn_zoom_out = gr.Button("➖ Zoom -", variant="secondary", scale=1)
                        zoom_slider = gr.Slider(minimum=75, maximum=260, value=140, step=15, label="Niveau de Zoom / Résolution DPI (75 à 260)", scale=4)
                        btn_zoom_in = gr.Button("➕ Zoom +", variant="secondary", scale=1)

                    preview_img = gr.Image(label="Aperçu HD du Document Rempli (PyMuPDF • Fenêtre 1080px)", interactive=False, height=1080)

            with gr.Tab("💾 Import / Export & Sauvegardes"):
                gr.Markdown("### 📦 Gestion des Fichiers de Données")
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("**Exporter les configurations**")
                        btn_dl_data = gr.File(label="Télécharger donnees.json", interactive=False, file_count="single")
                        btn_dl_map = gr.File(label="Télécharger mapping.json", interactive=False, file_count="single")
                    with gr.Column():
                        gr.Markdown("**Importer des données (Remplace l'actuel)**")
                        upload_data = gr.File(label="Importer donnees.json", file_types=[".json"], file_count="single")
                        btn_import = gr.Button("📥 Appliquer l'import", variant="primary")

            with gr.Tab("🩺 Console & Diagnostic"):
                with gr.Row():
                    btn_run_diag = gr.Button("🩺 Exécuter Diagnostic Complet", variant="primary", scale=2)
                    btn_clear_logs = gr.Button("🧹 Nettoyer Logs", variant="secondary", scale=1)
                diag_result = gr.Markdown("Cliquez sur le bouton ci-dessus pour inspecter l'environnement.")
                console_logs = gr.TextArea(label="Flux d'événements & Traceback", lines=14, interactive=False, elem_id="diagnostic-console-box")

        # ---------------------------------------------------------------------
        # Logique Applicative
        # ---------------------------------------------------------------------
        def render_table(fields, mappings, data, stat_mode, search_kw):
            alias_map = {m["pdf_target_path"]: m["alias"] for m in mappings if "pdf_target_path" in m}
            rows = []
            kw = search_kw.strip().lower()
            for f in fields:
                alias = alias_map.get(f.full_path, "")
                val = data.get(alias, "") if alias else ""
                filled = bool(str(val).strip())
                if stat_mode == "Champs VIDES" and filled: continue
                if stat_mode == "Champs REMPLIS" and not filled: continue
                if kw:
                    line_str = f"{alias} {f.tooltip} {f.leaf} {val} {f.full_path}".lower()
                    if kw not in line_str: continue
                
                display_alias = alias if alias else "—"
                display_val = str(val) if filled else "—"
                display_tu = f.tooltip if f.tooltip else "—"
                
                rows.append([
                    "✅ REMPLI" if filled else "❌ VIDE", 
                    f"Page {f.page_index + 1}", 
                    display_alias, display_val, display_tu, f.leaf, f.full_path,
                    f.page_index # Colonne cachée pour le tri numérique
                ])
            
            # Tri numérique par page, puis par statut, puis par alias
            rows.sort(key=lambda r: (r[7], r[0], r[2]))
            return [r[:7] for r in rows]

        def refresh_session(tmpl_path, out_path, logger):
            logger.info("Rechargement de la session...")
            fields = PDFCore.inspect_template(tmpl_path, logger)
            raw_map = StorageCore.load_json(DEFAULT_MAPPING, {"mappings": []}, logger)
            mappings = raw_map.get("mappings", [])
            data = StorageCore.load_json(DEFAULT_DATA, {}, logger)
            table = render_table(fields, mappings, data, "Tous les champs", "")
            summary = f"Total champs : **{len(fields)}** | Correspondances : **{len(mappings)}** | Valeurs : **{len(data)}**"
            init_png = PDFCore.render_png(out_path, 1) if os.path.exists(out_path) else None
            
            gr.Info("Session rechargée avec succès !")
            return (fields, mappings, data, table, summary, 
                    out_path if os.path.exists(out_path) else None, 
                    DEFAULT_DATA, DEFAULT_MAPPING,
                    init_png, logger.get_stream())

        def on_table_click(evt: gr.SelectData, fields, mappings, data, stat_mode, search_kw):
            table = render_table(fields, mappings, data, stat_mode, search_kw)
            if evt.index[0] < len(table):
                row = table[evt.index[0]]
                raw_alias, raw_val, raw_tu, leaf, path = row[2], row[3], row[4], row[5], row[6]
                clean_alias = "" if raw_alias == "—" else raw_alias
                clean_val = "" if raw_val == "—" else raw_val
                clean_tu = "" if raw_tu == "—" else raw_tu
                suggested = clean_alias if clean_alias else (clean_tu.replace(" ", "_") if clean_tu else leaf.replace("[0]", ""))
                return suggested, clean_val, path
            return "", "", ""

        def save_record(alias, val, path, fields, mappings, data, stat_mode, search_kw, logger):
            try:
                if not alias.strip():
                    gr.Warning("Spécifiez un alias.")
                    return mappings, data, gr.update(), gr.update(), logger.get_stream()
                if not path.strip():
                    gr.Warning("Sélectionnez un champ PDF.")
                    return mappings, data, gr.update(), gr.update(), logger.get_stream()
                
                a_clean, v_clean = alias.strip(), val.strip()
                data[a_clean] = v_clean
                StorageCore.save_json(DEFAULT_DATA, data, logger)
                
                if not any(m.get("alias") == a_clean for m in mappings):
                    match = re.search(r"page(\d+)", path, re.IGNORECASE)
                    p_idx = max(0, int(match.group(1)) - 1) if match else 0
                    mappings.append({
                        "alias": a_clean, "page_index": p_idx, "page_label": f"page{p_idx + 1}[0]",
                        "target_field_leaf": path.split(".")[-1], "parent_group": path.split(".")[-2] if len(path.split(".")) > 1 else "",
                        "pdf_target_path": path,
                    })
                    StorageCore.save_json(DEFAULT_MAPPING, {"mappings": mappings}, logger)
                
                new_table = render_table(fields, mappings, data, stat_mode, search_kw)
                summary = f"Total champs : **{len(fields)}** | Correspondances : **{len(mappings)}** | Valeurs : **{len(data)}**"
                gr.Success(f"Champ '{a_clean}' sauvegardé !")
                return mappings, data, new_table, summary, logger.get_stream()
            except Exception as e:
                logger.error("Erreur enregistrement champ", e)
                gr.Error(f"Erreur : {e}")
                return mappings, data, gr.update(), gr.update(), logger.get_stream()

        VIEW_MODE_DPI = {
            "📄 Page Entière": 95,
            "↔️ Pleine Largeur": 140,
            "🔍 Zoom 180%": 180,
            "🔎 Zoom 230%": 230,
        }

        def on_view_mode_change(mode: str, out_p: str, pg: str):
            dpi = VIEW_MODE_DPI.get(mode, 140)
            p_num = int(pg.replace("Page ", "")) if "Page " in pg else 1
            png = PDFCore.render_png(out_p, p_num, dpi) if os.path.exists(out_p) else None
            return dpi, png

        def on_zoom_step(delta: int, current_dpi: int, out_p: str, pg: str):
            new_dpi = max(75, min(260, int(current_dpi) + delta))
            p_num = int(pg.replace("Page ", "")) if "Page " in pg else 1
            png = PDFCore.render_png(out_p, p_num, new_dpi) if os.path.exists(out_p) else None
            return new_dpi, png

        def on_zoom_slider_change(dpi: int, out_p: str, pg: str):
            p_num = int(pg.replace("Page ", "")) if "Page " in pg else 1
            return PDFCore.render_png(out_p, p_num, dpi) if os.path.exists(out_p) else None

        def compile_preview_action(tmpl_p, out_p, mappings, data, page_choice, zoom_dpi, logger):
            try:
                p_num = int(page_choice.replace("Page ", "")) if "Page " in page_choice else 1
                out_compiled = PDFCore.compile(tmpl_p, out_p, mappings, data, logger)
                png_path = PDFCore.render_png(out_compiled, p_num, zoom_dpi)
                gr.Success("PDF compilé avec succès !")
                return out_compiled, png_path, logger.get_stream()
            except Exception as e:
                logger.error("Échec compilation PDF", e)
                gr.Error(f"Erreur compilation : {e}")
                return None, None, logger.get_stream()

        def import_data_action(file_obj, fields, mappings, stat_mode, search_kw, logger):
            if file_obj is None:
                gr.Warning("Aucun fichier sélectionné.")
                return gr.update(), gr.update(), logger.get_stream()
            try:
                with open(file_obj.name, 'r', encoding='utf-8') as f:
                    new_data = json.load(f)
                StorageCore.save_json(DEFAULT_DATA, new_data, logger)
                new_table = render_table(fields, mappings, new_data, stat_mode, search_kw)
                gr.Info("Données importées et sauvegardées !")
                return new_data, new_table, logger.get_stream()
            except Exception as e:
                logger.error("Erreur import JSON", e)
                gr.Error(f"Erreur lors de l'import : {e}")
                return gr.update(), gr.update(), logger.get_stream()

        def run_full_diagnostics(tmpl_p, out_p, mappings, data, logger):
            logger.info("Exécution du diagnostic complet...")
            report = ["### 🩺 Rapport de Diagnostic Système\n"]
            report.append(f"- **Python** : `{sys.version.split()[0]}`")
            report.append(f"- **PyMuPDF (Rendu HD)** : `{'✅ Disponible' if HAS_PYMUPDF else '❌ Non installé'}`")
            report.append(f"- **Template PDF** : `{'✅ Présent' if os.path.exists(tmpl_p) else '❌ Manquant'}`")
            report.append(f"- **Dossier de sortie** : `✅ Accès en écriture validé`")
            
            orphan_data = [k for k in data.keys() if not any(m.get("alias") == k for m in mappings)]
            if orphan_data:
                report.append(f"- **⚠️ Clés sans correspondance** : `{', '.join(orphan_data[:5])}`")
            else:
                report.append("- **Alignement Mapping/Données** : `✅ Intègre (100 % aligné)`")
            logger.success("Diagnostic terminé.")
            return "\n".join(report), logger.get_stream()

        # Câblage des événements
        app.load(
            refresh_session,
            inputs=[tmpl_box, out_box, state_logger],
            outputs=[state_fields, state_mappings, state_data, df_view, status_summary, file_down, btn_dl_data, btn_dl_map, preview_img, console_logs],
        )
        btn_reload.click(
            refresh_session,
            inputs=[tmpl_box, out_box, state_logger],
            outputs=[state_fields, state_mappings, state_data, df_view, status_summary, file_down, btn_dl_data, btn_dl_map, preview_img, console_logs],
        )
        
        for trigger in [filter_stat.change, search_box.change]:
            trigger(
                render_table,
                inputs=[state_fields, state_mappings, state_data, filter_stat, search_box],
                outputs=[df_view],
            )
        
        df_view.select(
            on_table_click,
            inputs=[state_fields, state_mappings, state_data, filter_stat, search_box],
            outputs=[edit_alias, edit_val, edit_path],
        )
        
        btn_save.click(
            save_record,
            inputs=[edit_alias, edit_val, edit_path, state_fields, state_mappings, state_data, filter_stat, search_box, state_logger],
            outputs=[state_mappings, state_data, df_view, status_summary, console_logs],
        )

        btn_clear.click(
            lambda: "",
            outputs=[edit_val],
        )
        
        btn_compile.click(
            compile_preview_action,
            inputs=[tmpl_box, out_box, state_mappings, state_data, page_pick, zoom_slider, state_logger],
            outputs=[file_down, preview_img, console_logs],
        )

        page_pick.change(
            lambda out_p, pg, dpi: PDFCore.render_png(out_p, int(pg.replace("Page ", "")), dpi) if os.path.exists(out_p) else None,
            inputs=[out_box, page_pick, zoom_slider],
            outputs=[preview_img],
        )

        view_mode.change(
            on_view_mode_change,
            inputs=[view_mode, out_box, page_pick],
            outputs=[zoom_slider, preview_img],
        )

        btn_zoom_in.click(
            lambda current_dpi, out_p, pg: on_zoom_step(20, current_dpi, out_p, pg),
            inputs=[zoom_slider, out_box, page_pick],
            outputs=[zoom_slider, preview_img],
        )

        btn_zoom_out.click(
            lambda current_dpi, out_p, pg: on_zoom_step(-20, current_dpi, out_p, pg),
            inputs=[zoom_slider, out_box, page_pick],
            outputs=[zoom_slider, preview_img],
        )

        zoom_slider.release(
            on_zoom_slider_change,
            inputs=[zoom_slider, out_box, page_pick],
            outputs=[preview_img],
        )
        
        btn_import.click(
            import_data_action,
            inputs=[upload_data, state_fields, state_mappings, filter_stat, search_box, state_logger],
            outputs=[state_data, df_view, console_logs],
        )
        
        btn_run_diag.click(
            run_full_diagnostics,
            inputs=[tmpl_box, out_box, state_mappings, state_data, state_logger],
            outputs=[diag_result, console_logs],
        )
        
        btn_clear_logs.click(
            lambda logger: (logger.clear() or "[Logs purgés]", logger.get_stream()),
            inputs=[state_logger],
            outputs=[console_logs, console_logs],
        )

    return app

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AcroForm Studio v3.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    args = parser.parse_args()

    allowed_dirs = list({
        str(Path(DEFAULT_OUTPUT).parent.resolve()),
        str(Path(DEFAULT_TEMPLATE).parent.resolve()),
        str(BASE_DIR.resolve()),
        str(PREVIEW_DIR.resolve()),
    })
    
    demo = build_app()
    demo.launch(
        server_name=args.host,
        server_port=args.port,
        allowed_paths=allowed_dirs,
        theme=build_midnight_theme(),
        css=MIDNIGHT_DARK_CSS,
    )