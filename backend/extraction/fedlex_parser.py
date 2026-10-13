"""Fedlex and Akoma Ntoso 3.0 Swiss Law Parser for RepoScroller.

Provides structured ingestion of Swiss Federal Law (Recueil systématique / Systematische Rechtssammlung),
preserving legal article boundaries, multilingual binding keys, and PDF reference associations.
"""

import os
import re
import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from backend.config import settings

logger = logging.getLogger("extraction.fedlex")

AKOMA_NTOSO_NS = {"an": "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"}

SWISS_LAW_CATALOG: Dict[str, Dict[str, str]] = {
    "101": {
        "short_fr": "Cst.", "short_de": "BV", "short_en": "Cst.", "short_it": "Cost.",
        "title_fr": "Constitution fédérale de la Confédération suisse",
        "title_de": "Bundesverfassung der Schweizerischen Eidgenossenschaft",
        "title_en": "Federal Constitution of the Swiss Confederation",
        "title_it": "Costituzione federale della Confederazione Svizzera",
    },
    "142.20": {
        "short_fr": "LEI", "short_de": "AIG", "short_en": "FNIA", "short_it": "LStI",
        "title_fr": "Loi fédérale sur les étrangers et l'intégration",
        "title_de": "Bundesgesetz über die Ausländerinnen und Ausländer und über die Integration",
        "title_en": "Federal Act on Foreign Nationals and Integration",
        "title_it": "Legge federale sugli stranieri e la loro integrazione",
    },
    "173.110": {
        "short_fr": "LTF", "short_de": "BGG", "short_en": "FSCA", "short_it": "LCA",
        "title_fr": "Loi sur le Tribunal fédéral",
        "title_de": "Bundesgerichtsgesetz",
        "title_en": "Federal Supreme Court Act",
        "title_it": "Legge sul Tribunale federale",
    },
    "210": {
        "short_fr": "CC", "short_de": "ZGB", "short_en": "CC", "short_it": "CC",
        "title_fr": "Code civil suisse",
        "title_de": "Schweizerisches Zivilgesetzbuch",
        "title_en": "Swiss Civil Code",
        "title_it": "Codice civile svizzero",
    },
    "220": {
        "short_fr": "CO", "short_de": "OR", "short_en": "CO", "short_it": "CO",
        "title_fr": "Code des obligations",
        "title_de": "Obligationenrecht",
        "title_en": "Swiss Code of Obligations",
        "title_it": "Codice delle obbligazioni",
    },
    "272": {
        "short_fr": "CPC", "short_de": "ZPO", "short_en": "CPC", "short_it": "CPC",
        "title_fr": "Code de procédure civile",
        "title_de": "Schweizerische Zivilprozessordnung",
        "title_en": "Civil Procedure Code",
        "title_it": "Codice di diritto processuale civile svizzero",
    },
    "273": {
        "short_fr": "PCF", "short_de": "BZP", "short_en": "FCPA", "short_it": "PCF",
        "title_fr": "Loi fédérale de procédure civile fédérale",
        "title_de": "Bundesgesetz über den Bundeszivilprozess",
        "title_en": "Federal Civil Procedure Act",
        "title_it": "Legge federale di procedura civile federale",
    },
    "281.1": {
        "short_fr": "LP", "short_de": "SchKG", "short_en": "DEBA", "short_it": "LEF",
        "title_fr": "Loi fédérale sur la poursuite pour dettes et la faillite",
        "title_de": "Bundesgesetz über Schuldbetreibung und Konkurs",
        "title_en": "Federal Act on Debt Enforcement and Bankruptcy",
        "title_it": "Legge federale sulla esecuzione e sul fallimento",
    },
    "311.0": {
        "short_fr": "CP", "short_de": "StGB", "short_en": "SCC", "short_it": "CP",
        "title_fr": "Code pénal suisse",
        "title_de": "Schweizerisches Strafgesetzbuch",
        "title_en": "Swiss Criminal Code",
        "title_it": "Codice penale svizzero",
    },
    "312.0": {
        "short_fr": "CPP", "short_de": "StPO", "short_en": "CrimPC", "short_it": "CPP",
        "title_fr": "Code de procédure pénale suisse",
        "title_de": "Schweizerische Strafprozessordnung",
        "title_en": "Swiss Criminal Procedure Code",
        "title_it": "Codice di procedura penale svizzero",
    },
    "702": {
        "short_fr": "LRS", "short_de": "ZWG", "short_en": "SHA", "short_it": "LSS",
        "title_fr": "Loi sur les résidences secondaires",
        "title_de": "Bundesgesetz über Zweitwohnungen",
        "title_en": "Second Homes Act",
        "title_it": "Legge sulle abitazioni secondarie",
    },
    "741.01": {
        "short_fr": "LCR", "short_de": "SVG", "short_en": "RTA", "short_it": "LCStr",
        "title_fr": "Loi fédérale sur la circulation routière",
        "title_de": "Strassenverkehrsgesetz",
        "title_en": "Road Traffic Act",
        "title_it": "Legge federale sulla circolazione stradale",
    },
    "830.1": {
        "short_fr": "LPGA", "short_de": "ATSG", "short_en": "LPGA", "short_it": "LPGA",
        "title_fr": "Loi fédérale sur la partie générale du droit des assurances sociales",
        "title_de": "Bundesgesetz über den Allgemeinen Teil des Sozialversicherungsrechts",
        "title_en": "Federal Act on General Aspects of Social Security Law",
        "title_it": "Legge federale sulla parte generale del diritto delle assicurazioni sociali",
    },
    "831.10": {
        "short_fr": "LAVS", "short_de": "AHVG", "short_en": "OASIA", "short_it": "LAVS",
        "title_fr": "Loi fédérale sur l'assurance-vieillesse et survivants",
        "title_de": "Bundesgesetz über die Alters- und Hinterlassenenversicherung",
        "title_en": "Federal Act on Old-Age and Survivors' Insurance",
        "title_it": "Legge federale sull'assicurazione per la vecchiaia e per i superstiti",
    },
}


def is_akoma_ntoso_xml(file_path: Path) -> bool:
    """Detect whether a file is an Akoma Ntoso 3.0 legal XML file."""
    if file_path.suffix.lower() != ".xml":
        return False

    name = file_path.name.lower()
    # Direct Fedlex naming pattern heuristics
    if re.match(r'^(rs|sr)[-_]\d+', name) or "fedlex" in name:
        return True

    # Check XML root element / namespaces without loading huge memory
    try:
        with open(file_path, "rb") as f:
            header_sample = f.read(2048).decode("utf-8", errors="ignore")
            if "legaldocml/ns/akn/3.0" in header_sample or "<akomaNtoso" in header_sample:
                return True
    except Exception:
        pass

    return False


def detect_sr_and_lang(file_path: Path, root: Optional[ET.Element] = None) -> Tuple[Optional[str], str]:
    """Extract SR code and language from file naming, directory structure, or XML metadata."""
    name = file_path.name
    sr_code = None
    lang = "fr"

    # Pattern 1: RS-{code}-{date}-{lang}.xml or SR-{code}-{date}-{lang}.xml
    m = re.search(r'^(?:RS|SR)[-_](\d+(?:\.\d+)?)[-_].*?[-_](FR|DE|IT|EN)\.xml$', name, re.IGNORECASE)
    if m:
        sr_code = m.group(1)
        lang = m.group(2).lower()
        return sr_code, lang

    # Pattern 2: Directory structure like SR_220/FR/...
    for parent in file_path.parents:
        p_name = parent.name
        if p_name.upper() in ["FR", "DE", "IT", "EN"]:
            lang = p_name.lower()
        m_sr = re.search(r'^SR[-_](\d+(?:\.\d+)?)$', p_name, re.IGNORECASE)
        if m_sr:
            sr_code = m_sr.group(1)

    # Pattern 3: Look in XML metadata if root element provided
    if root is not None:
        if not sr_code:
            frbr_num = root.find(".//an:FRBRnumber", AKOMA_NTOSO_NS)
            if frbr_num is not None and frbr_num.get("value"):
                sr_code = frbr_num.get("value")

        if not lang or lang == "fr":
            frbr_lang = root.find(".//an:FRBRlanguage", AKOMA_NTOSO_NS)
            if frbr_lang is not None and frbr_lang.get("language"):
                lang = frbr_lang.get("language").lower()

    return sr_code, lang


def load_manifest(search_path: Path) -> Dict[str, Any]:
    """Search upwards for a manifest.json file from the Fedlex library."""
    current = search_path if search_path.is_dir() else search_path.parent
    for _ in range(5):
        manifest_file = current / "manifest.json"
        if manifest_file.exists():
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                    logger.debug(f"Loaded manifest from {manifest_file} ({len(manifest)} SR entries)")
                    return manifest
            except Exception as e:
                logger.warning(f"Failed to load manifest.json at {manifest_file}: {e}")
        if current.parent == current:
            break
        current = current.parent
    return {}


def parse_akoma_ntoso_xml(file_path: Path, manifest: Optional[Dict[str, Any]] = None) -> Tuple[str, Dict[str, Any]]:
    """Parse an Akoma Ntoso 3.0 XML legal document into structured articles and full text.
    
    Returns:
        Tuple of (combined_text_for_ledger, metadata_dict)
    """
    metadata: Dict[str, Any] = {
        "is_fedlex_xml": True,
        "page_count": 1,
        "has_digital_signature": False,
        "articles": [],
        "articles_count": 0,
        "binding_keys": [],
        "sr_code": "",
        "lang": "fr",
        "title": "",
        "short_form": "",
        "pdf_reference_path": "",
    }

    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
    except Exception as e:
        logger.error(f"Failed to parse XML file '{file_path.name}': {e}")
        metadata["extraction_error"] = str(e)
        return "", metadata

    sr_code, lang = detect_sr_and_lang(file_path, root)
    sr_code = sr_code or "UNKNOWN"
    metadata["sr_code"] = sr_code
    metadata["lang"] = lang

    # Resolve Title and Short Form
    catalog_entry = SWISS_LAW_CATALOG.get(sr_code, {})
    title = catalog_entry.get(f"title_{lang}") or catalog_entry.get("title_fr")
    if not title:
        doc_title_el = root.find(".//an:docTitle", AKOMA_NTOSO_NS)
        if doc_title_el is not None:
            title = "".join(doc_title_el.itertext()).strip()
        else:
            title = f"SR {sr_code}"
    metadata["title"] = title

    short_form = catalog_entry.get(f"short_{lang}") or catalog_entry.get("short_fr") or ""
    metadata["short_form"] = short_form

    # Resolve PDF Reference from manifest or filesystem
    pdf_ref = ""
    if manifest and sr_code in manifest:
        lang_key = lang.upper()
        sr_entry = manifest[sr_code]
        if lang_key in sr_entry and "pdf" in sr_entry[lang_key]:
            pdf_ref = sr_entry[lang_key]["pdf"]
            if not os.path.isabs(pdf_ref):
                # Resolve relative to manifest directory
                manifest_dir = file_path.parent
                candidate = manifest_dir / pdf_ref
                if candidate.exists():
                    pdf_ref = str(candidate.resolve())

    if not pdf_ref:
        # Check for sibling PDF with matching name pattern
        pdf_candidate = file_path.with_suffix(".pdf")
        if pdf_candidate.exists():
            pdf_ref = str(pdf_candidate.resolve())

    metadata["pdf_reference_path"] = pdf_ref

    # Extract Articles
    articles_found = root.findall(".//an:article", AKOMA_NTOSO_NS)
    articles_data: List[Dict[str, Any]] = []
    combined_passages: List[str] = []

    for idx, art in enumerate(articles_found):
        # 1. Article Number (<an:num>)
        art_num_el = art.find("an:num", AKOMA_NTOSO_NS)
        art_num = "".join(art_num_el.itertext()).strip() if art_num_el is not None else f"Art. {idx+1}"

        # 2. Heading (<an:heading>)
        heading_el = art.find("an:heading", AKOMA_NTOSO_NS)
        if heading_el is None:
            parent_level = art.find("..")
            if parent_level is not None:
                heading_el = parent_level.find("an:heading", AKOMA_NTOSO_NS)
        article_heading = "".join(heading_el.itertext()).strip() if heading_el is not None else ""

        # 3. Paragraphs (<an:p>)
        paragraphs = []
        for p in art.findall(".//an:p", AKOMA_NTOSO_NS):
            p_text = "".join(p.itertext()).strip()
            if p_text:
                paragraphs.append(p_text)

        text_content = " ".join(paragraphs).strip()
        if not text_content:
            continue

        # Format Universal Binding Key: e.g. "220_Art. 1"
        clean_art_num = re.sub(r'\s+', ' ', art_num)
        binding_key = f"{sr_code}_{clean_art_num}"

        heading_str = f" — {article_heading}" if article_heading else ""
        short_label = f" ({short_form} SR {sr_code})" if short_form else f" (SR {sr_code})"
        full_passage = f"passage: {title}{short_label}, {art_num}{heading_str}: {text_content}"

        art_payload = {
            "sr_code": sr_code,
            "article_num": art_num,
            "lang": lang,
            "title": title,
            "short_form": short_form,
            "article_heading": article_heading,
            "binding_key": binding_key,
            "paragraphs": paragraphs,
            "text_content": text_content,
            "full_text": full_passage,
            "chunk_index": idx,
            "pdf_reference_path": pdf_ref,
        }
        articles_data.append(art_payload)
        combined_passages.append(full_passage)

    metadata["articles"] = articles_data
    metadata["articles_count"] = len(articles_data)
    metadata["binding_keys"] = [a["binding_key"] for a in articles_data]
    metadata["page_count"] = max(1, len(articles_data) // 5)

    full_text = "\n\n".join(combined_passages).strip()
    return full_text, metadata
