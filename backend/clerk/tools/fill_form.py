#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
Formular-Assistent : Gesuch um unentgeltliche Rechtspflege (Art. 119 ZPO)
=============================================================================
Professional-grade, Object-Oriented PDF Form Population Engine with:
  - Rich interactive terminal UI (Tables, Trees, Panels, Status spinners)
  - Strict atomic write operations preventing file corruption
  - Robust error handling and input validation
  - Intelligent multi-page AcroForm schema resolver & friendly alias mapping
=============================================================================
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Third-party dependencies
try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    print("[CRITICAL] 'pypdf' is not installed. Please install it via: pip install pypdf", file=sys.stderr)
    sys.exit(1)

try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.theme import Theme
    from rich.tree import Tree
    from rich.traceback import install as install_rich_traceback
    install_rich_traceback(show_locals=False)
except ImportError:
    print("[CRITICAL] 'rich' is not installed. Please install it via: pip install rich", file=sys.stderr)
    sys.exit(1)


# =============================================================================
# Custom Exception Hierarchy
# =============================================================================

class PDFFormError(Exception):
    """Base exception for all PDF form processing errors."""


class SourceFileNotFoundError(PDFFormError):
    """Raised when the specified template PDF cannot be found or read."""


class InvalidPDFError(PDFFormError):
    """Raised when the input file is not a valid PDF or has no fillable form fields."""


class FormValidationError(PDFFormError):
    """Raised when form input data fails required validation checks."""


class AtomicWriteError(PDFFormError):
    """Raised when atomic file persistence fails."""


# =============================================================================
# Rich UI & Console Theme
# =============================================================================

CUSTOM_THEME = Theme({
    "info": "cyan",
    "success": "bold green",
    "warning": "bold yellow",
    "error": "bold red",
    "header": "bold magenta",
    "muted": "dim white",
    "accent": "bold deep_sky_blue1",
})

console = Console(theme=CUSTOM_THEME)


class ConsoleUI:
    """Manages visual presentation, telemetry, and structured CLI reporting."""

    @staticmethod
    def banner(title: str, subtitle: Optional[str] = None) -> None:
        """Renders an executive header panel."""
        text = f"[header]{title}[/]"
        if subtitle:
            text += f"\n[muted]{subtitle}[/]"
        console.print(Panel(text, box=box.ROUNDED, border_style="deep_sky_blue1", expand=False))

    @staticmethod
    def info(msg: str) -> None:
        console.print(f"[[accent]INFO[/]] {msg}")

    @staticmethod
    def success(msg: str) -> None:
        console.print(f"[[success]SUCCESS[/]] {msg}")

    @staticmethod
    def warning(msg: str) -> None:
        console.print(f"[[warning]WARNING[/]] {msg}")

    @staticmethod
    def error(msg: str, details: Optional[str] = None) -> None:
        console.print(f"[[error]ERROR[/]] [bold red]{msg}[/]")
        if details:
            console.print(Panel(details, title="[error]Diagnostic Details[/]", border_style="red"))

    @staticmethod
    def render_field_table(records: List[Dict[str, Any]]) -> None:
        """Displays a structured table of resolved form fields."""
        table = Table(
            title="AcroForm Field Injection Plan",
            box=box.SIMPLE_HEAVY,
            header_style="bold cyan",
            show_lines=False,
        )
        table.add_column("Status", justify="center", style="bold", width=8)
        table.add_column("Page", justify="center", width=6)
        table.add_column("Logical Alias / Key", style="accent", width=28)
        table.add_column("PDF Target Field", style="muted", width=36)
        table.add_column("Value Preview", style="white")

        for r in records:
            status = "[green]MATCH[/]" if r["matched"] else "[yellow]SKIP[/]"
            page_str = str(r.get("page_index", "-"))
            alias = r["alias"]
            target = r.get("target_field", "N/A")
            val = str(r["value"])
            if len(val) > 45:
                val = val[:42] + "..."
            table.add_row(status, page_str, alias, target, val)

        console.print(table)


# =============================================================================
# Atomic File Writer (Atomic OO File Safety)
# =============================================================================

class AtomicFileWriter:
    """
    Context manager ensuring atomic file writing.
    Writes to a temporary file located in the target directory, flushes to disk,
    and performs an atomic rename via os.replace. Ensures zero risk of corrupted
    or truncated outputs upon interruption or errors.
    """

    def __init__(self, target_path: Path):
        self.target_path = Path(target_path).resolve()
        self.target_dir = self.target_path.parent
        self.temp_file: Optional[tempfile.NamedTemporaryFile] = None
        self.temp_path: Optional[Path] = None

    def __enter__(self) -> Path:
        try:
            self.target_dir.mkdir(parents=True, exist_ok=True)
            # Create temporary file in same filesystem for atomic rename
            self.temp_file = tempfile.NamedTemporaryFile(
                dir=self.target_dir,
                prefix=f".tmp_{self.target_path.stem}_",
                suffix=".tmp",
                delete=False,
            )
            self.temp_path = Path(self.temp_file.name)
            self.temp_file.close()  # Hand over path to writer
            return self.temp_path
        except Exception as e:
            raise AtomicWriteError(f"Failed to initialize atomic write buffer: {e}") from e

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            # An error occurred: remove temporary file without modifying target
            if self.temp_path and self.temp_path.exists():
                try:
                    self.temp_path.unlink()
                except OSError:
                    pass
            return

        # Success path: atomic swap
        if not self.temp_path or not self.temp_path.exists():
            raise AtomicWriteError("Temporary output file was not generated.")

        try:
            # os.replace is atomic on both POSIX and Windows
            os.replace(self.temp_path, self.target_path)
        except OSError as e:
            if self.temp_path.exists():
                try:
                    self.temp_path.unlink()
                except OSError:
                    pass
            raise AtomicWriteError(f"Atomic replacement of target file failed: {e}") from e


# =============================================================================
# Domain Data Model (UP Form Payload)
# =============================================================================

def normalize_field_value(field_name: str, value: Any) -> str:
    """Normalizes interactive widget values (checkboxes, radio groups, buttons)."""
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


@dataclass
class UPFormPayload:
    """Structured data model for Cantonal Legal Aid (Art. 119 ZPO)."""
    # 1. Gesuchsteller (Applicant)
    name: str = "Falempin"
    vorname: str = "Antoine Guillaume"
    strasse: str = "Rebenstrasse"
    hausnummer: str = "29b"
    plz: str = "8913"
    ort: str = "Ottenbach"
    telefon: str = "+41 76 411 68 99"
    mobil: str = "+41 76 411 68 99"
    email: str = "antoine.falempin37@gmail.com"
    geburtsdatum: str = "23.06.1975"
    nationalitaet: str = "Frankreich"
    heimatort: str = "Tours"
    zivilstand: str = "verheiratet"
    beruf: str = "IT- / Automationsingenieur (aktuell erwerbslos / ALV ausgesteuert / kein Einkommen)"
    sprache: str = "Französisch / Deutsch / English"
    uebersetzer_erforderlich: str = "Ja"

    # 2. Ehepartnerin (Partner)
    ehepartner_name: str = "Ranadireksa"
    ehepartner_vorname: str = "Dinda Gayatri"
    ehepartner_geburtsdatum: str = "20.06.1976"
    ehepartner_strasse: str = "Rebenstrasse"
    ehepartner_hausnummer: str = "29b"
    ehepartner_plz: str = "8913"
    ehepartner_ort: str = "Ottenbach"
    ehepartner_nationalitaet: str = "Indonesien (Aufenthaltsbewilligung B seit Sept. 2025)"
    ehepartner_heimatort: str = "Bandung (Indonesien)"
    ehepartner_beruf: str = "Akademikerin / Remote-Dozentin (keine Anstellung in CH, Einkommen verbleibt in Indonesien)"
    ehepartner_arbeitgeber: str = "Universitas Widyatama (Bandung, Indonesien)"

    # 3. Kinder (Children)
    kind1_name: str = "Falempin-Inapogui"
    kind1_vorname: str = "Aloïs Madiba"
    kind1_geburtsdatum: str = "19.06.2011"
    kind1_haushalt: str = "Nein"

    # 4. Kinder der Partnerin
    partnerkind1_name: str = "Rifqi"
    partnerkind1_vorname: str = "Hikari Anandi"
    partnerkind1_geburtsdatum: str = "05.09.2003"
    partnerkind1_haushalt: str = "Nein"
    partnerkind2_name: str = "Sakki"
    partnerkind2_vorname: str = "Hiro Anandi"
    partnerkind2_geburtsdatum: str = "12.02.2007"
    partnerkind2_haushalt: str = "Nein"

    # 5. Andere Personen im Haushalt
    weitere_personen_haushalt: str = "Ehefrau Dinda Gayatri Ranadireksa (B-Bewilligung, gemeinsamer Haushalt in Ottenbach)"

    # Sozialhilfe
    sozialhilfe_bezug: str = "Nein"
    sozialhilfe_zeitspanne: str = "Noch nicht bezogen; Antragsformular ist in Vorbereitung (Aussteuerung ALV eingetreten)"

    # 6 & 7. Rechtsbegehren & Begründung (Procedural Claims)
    hauptsache_rechtsbegehren: str = (
        "Siehe eingereichtes Hauptgesuch um Wohnungsausweisung "
        "(Art. 257 / Art. 260a ZPO) vom 22. August 2026 (Verfahren UP 2026 121 / ES 2026 880)."
    )
    hauptsache_begruendung: str = (
        "Vollumfänglich begründet im Ausweisungsgesuch vom 22.08.2026 "
        "(Alleineigentum, titellose Besetzung, finanzielle Notlage und fehlende Verfügbarkeit der Liegenschaft)."
    )

    # 8. Unentgeltlicher Rechtsbeistand (Counsel)
    anwalt_benoetigt: str = "Ja"
    anwalt_grund: str = (
        "Zur Wahrung der Waffengleichheit, da die Gegenpartei anwaltlich vertreten ist (RA Simon Rückstein). "
        "Die Sache weist erhebliche Komplexität auf (Art. 257 ZPO, Eigentums- und Familienverhältnisse). "
        "Zudem fremde Verfahrenssprache (Muttersprache Französisch) und gesundheitliche Erschöpfung (Art. 118 Abs. 1 lit. c ZPO)."
    )
    anwalt_wunsch: str = "Dem Kantonsgericht zur amtlichen Beiordnung anheimgestellt (vorzugsweise zweisprachig FR/DE via Zuger Anwaltsverband)"

    # 9. Rechtsschutz & Anwaltsvorschüsse
    rechtsschutz_besteht: str = "Nein"
    rechtsschutz_umfang: str = "Keine Deckung für familien- und mietrechtliche Streitigkeiten"
    anwalt_vorschuss: str = "0.00"

    # 11. Einkommen (Income)
    einkommen_nettolohn: str = "0.00"
    einkommen_alv: str = "0.00"
    einkommen_total: str = "0.00"
    einkommen_partner: str = "0.00"

    # 12. Auslagen (Expenses)
    auslagen_mietzins: str = "2'424.27"
    auslagen_hypothekarzins: str = "2'732.11"
    auslagen_krankenkasse: str = "875.80"
    auslagen_versicherungen: str = "702.51"
    auslagen_alimente: str = "1'931.00"
    auslagen_kind_direkt: str = "403.08"
    auslagen_total: str = "9'068.77"

    # 14 & 15. Vermögen & Schulden (Assets & Liabilities)
    konti_saldi: str = "PostFinance CHF -7'831.23 (Überziehung / Pendente Aufträge CHF 7'183.05)"
    liegenschaft_steinhausen: str = "Eschenstrasse 7, 6312 Steinhausen (Verkehrswert ca. CHF 800'000.–; blockiert, kein Nutzen, keine freie Veräusserbarkeit)"
    grundpfandschuld_steinhausen: str = "700'000.00"

    # Custom dynamic mappings or raw field overrides
    raw_overrides: Dict[str, str] = field(default_factory=dict)

    def to_alias_dict(self) -> Dict[str, str]:
        """Flattens payload into canonical friendly keys."""
        data = {
            "Name": self.name,
            "Vorname": self.vorname,
            "Strasse": self.strasse,
            "Hausnummer": self.hausnummer,
            "PLZ": self.plz,
            "Ort": self.ort,
            "Telefon": self.telefon,
            "Mobil": self.mobil,
            "Email": self.email,
            "Geburtsdatum": self.geburtsdatum,
            "Nationalitaet": self.nationalitaet,
            "Heimatort": self.heimatort,
            "Zivilstand": self.zivilstand,
            "Beruf": self.beruf,
            "Sprache": self.sprache,
            "Uebersetzer_erforderlich": self.uebersetzer_erforderlich,
            "Ehepartner_Name": self.ehepartner_name,
            "Ehepartner_Vorname": self.ehepartner_vorname,
            "Ehepartner_Geburtsdatum": self.ehepartner_geburtsdatum,
            "Ehepartner_Strasse": self.ehepartner_strasse,
            "Ehepartner_Hausnummer": self.ehepartner_hausnummer,
            "Ehepartner_PLZ": self.ehepartner_plz,
            "Ehepartner_Ort": self.ehepartner_ort,
            "Ehepartner_Nationalitaet": self.ehepartner_nationalitaet,
            "Ehepartner_Heimatort": self.ehepartner_heimatort,
            "Ehepartner_Beruf": self.ehepartner_beruf,
            "Ehepartner_Arbeitgeber": self.ehepartner_arbeitgeber,
            "Kind1_Name": self.kind1_name,
            "Kind1_Vorname": self.kind1_vorname,
            "Kind1_Geburtsdatum": self.kind1_geburtsdatum,
            "Kind1_Haushalt": self.kind1_haushalt,
            "PartnerKind1_Name": self.partnerkind1_name,
            "PartnerKind1_Vorname": self.partnerkind1_vorname,
            "PartnerKind1_Geburtsdatum": self.partnerkind1_geburtsdatum,
            "PartnerKind1_Haushalt": self.partnerkind1_haushalt,
            "PartnerKind2_Name": self.partnerkind2_name,
            "PartnerKind2_Vorname": self.partnerkind2_vorname,
            "PartnerKind2_Geburtsdatum": self.partnerkind2_geburtsdatum,
            "PartnerKind2_Haushalt": self.partnerkind2_haushalt,
            "WeiterePersonen_Haushalt": self.weitere_personen_haushalt,
            "Sozialhilfe_Bezug": self.sozialhilfe_bezug,
            "Sozialhilfe_Zeitspanne": self.sozialhilfe_zeitspanne,
            "Hauptsache_Rechtsbegehren": self.hauptsache_rechtsbegehren,
            "Hauptsache_Begruendung": self.hauptsache_begruendung,
            "Anwalt_Benoetigt": self.anwalt_benoetigt,
            "Anwalt_Grund": self.anwalt_grund,
            "Anwalt_Wunsch": self.anwalt_wunsch,
            "Rechtsschutz_Besteht": self.rechtsschutz_besteht,
            "Rechtsschutz_Umfang": self.rechtsschutz_umfang,
            "Anwalt_Vorschuss": self.anwalt_vorschuss,
            "Einkommen_Nettolohn": self.einkommen_nettolohn,
            "Einkommen_ALV": self.einkommen_alv,
            "Einkommen_Total": self.einkommen_total,
            "Einkommen_Partner": self.einkommen_partner,
            "Auslagen_Mietzins": self.auslagen_mietzins,
            "Auslagen_Hypothekarzins": self.auslagen_hypothekarzins,
            "Auslagen_Krankenkasse": self.auslagen_krankenkasse,
            "Auslagen_Versicherungen": self.auslagen_versicherungen,
            "Auslagen_Alimente": self.auslagen_alimente,
            "Auslagen_Kind_Direkt": self.auslagen_kind_direkt,
            "Auslagen_Total": self.auslagen_total,
            "Konti_Saldi": self.konti_saldi,
            "Liegenschaft_Steinhausen": self.liegenschaft_steinhausen,
            "Grundpfandschuld_Steinhausen": self.grundpfandschuld_steinhausen,
        }
        data.update(self.raw_overrides)
        return data


# =============================================================================
# AcroForm Catalog & Schema Resolver (Intelligent Page-Scoped Dispatcher)
# =============================================================================

class AcroFieldResolver:
    """
    Introspects PDF AcroForm fields, caches structural hierarchy,
    and maps friendly semantic aliases to fully-qualified PDF field paths
    with strict page-targeting.
    """

    # Alias definitions mapped to target (page_index, leaf_name, parent_filter)
    CANONICAL_TARGETS: Dict[str, Tuple[int, str, Optional[str]]] = {
        # Page 1 (Index 0): Applicant
        "Name": (0, "suisseIDLastName[0]", "klagendePartei"),
        "Vorname": (0, "suisseIDFirstName[0]", "klagendePartei"),
        "Strasse": (0, "street[0]", "klagendePartei"),
        "Hausnummer": (0, "houseNumber[0]", "klagendePartei"),
        "PLZ": (0, "swissZipCode[0]", "klagendePartei"),
        "Ort": (0, "municipalityName[0]", "klagendePartei"),
        "Telefon": (0, "phoneNumber[0]", "klagendePartei"),
        "Mobil": (0, "phoneNumberMobile[0]", "klagendePartei"),
        "Email": (0, "eCHformUserEmail[0]", "klagendePartei"),
        "Sprache": (0, "language[0]", "klagendePartei"),
        "Uebersetzer_erforderlich": (0, "requireTranslation[0]", "klagendePartei"),
        "Geburtsdatum": (0, "suisseIDDateOfBirth[0]", "klagendePartei"),
        "Beruf": (0, "profession[0]", "klagendePartei"),
        "Heimatort": (0, "suisseIDPlaceOfBirth[0]", "klagendePartei"),
        "Nationalitaet": (0, "suisseIDOrigin[0]", "klagendePartei"),
        "Zivilstand": (0, "maritalStatus[0]", "klagendePartei"),

        # Page 2 (Index 1): Partner (Section 2)
        "Ehepartner_Name": (1, "suisseIDLastName[0]", "partner"),
        "Ehepartner_Vorname": (1, "suisseIDFirstName[0]", "partner"),
        "Ehepartner_Strasse": (1, "street[0]", "partner"),
        "Ehepartner_Hausnummer": (1, "houseNumber[0]", "partner"),
        "Ehepartner_Ort": (1, "municipalityName[0]", "partner"),
        "Ehepartner_PLZ": (1, "swissZipCode[0]", "partner"),
        "Ehepartner_Telefon": (1, "phoneNumber[0]", "partner"),
        "Ehepartner_Mobil": (1, "phoneNumberMobile[0]", "partner"),
        "Ehepartner_Email": (1, "eCHformUserEmail[0]", "partner"),
        "Ehepartner_Geburtsdatum": (1, "suisseIDDateOfBirth[0]", "partner"),
        "Ehepartner_Beruf": (1, "profession[0]", "partner"),
        "Ehepartner_Heimatort": (1, "suisseIDPlaceOfBirth[0]", "partner"),
        "Ehepartner_Nationalitaet": (1, "suisseIDOrigin[0]", "partner"),
        "Ehepartner_Arbeitgeber": (1, "profession[1]", "partner"),

        # Page 2 (Index 1): Section 3 Eigene Kinder (Child 1: Aloïs Madiba)
        "Kind1_Name": (1, "suisseIDLastName[0]", "eigeneKinder"),
        "Kind1_Vorname": (1, "suisseIDFirstName[0]", "eigeneKinder"),
        "Kind1_Geburtsdatum": (1, "suisseIDDateOfBirth[0]", "eigeneKinder"),
        "Kind1_Haushalt": (1, "RadioButtonList[0]", "eigeneKinder"),

        # Page 3 (Index 2): Section 4 Kinder der Partnerin (Child 1: Hikari, Child 2: Hiro)
        "PartnerKind1_Name": (2, "suisseIDLastName[0]", "eigeneKinder"),
        "PartnerKind1_Vorname": (2, "suisseIDFirstName[0]", "eigeneKinder"),
        "PartnerKind1_Geburtsdatum": (2, "suisseIDDateOfBirth[0]", "eigeneKinder"),
        "PartnerKind1_Haushalt": (2, "RadioButtonList[0]", "eigeneKinder"),
        "PartnerKind2_Name": (2, "suisseIDLastName[1]", "eigeneKinder"),
        "PartnerKind2_Vorname": (2, "suisseIDFirstName[1]", "eigeneKinder"),
        "PartnerKind2_Geburtsdatum": (2, "suisseIDDateOfBirth[1]", "eigeneKinder"),
        "PartnerKind2_Haushalt": (2, "RadioButtonList[1]", "eigeneKinder"),

        # Page 4 (Index 3): Section 5 Andere Personen & Section 6 Rechtsbegehren
        "WeiterePersonen_Haushalt": (3, "suisseIDLastName[0]", "eigeneKinder"),
        "Hauptsache_Rechtsbegehren": (3, "communications[0]", "rechtsbegehren"),

        # Page 5 (Index 4): Motivation & Legal Aid & Rechtsschutz & Sozialhilfe
        "Hauptsache_Begruendung": (4, "communications[0]", "Streitgegenstand"),
        "Anwalt_Benoetigt": (4, "RadioButtonList[0]", "rechtsbeistand"),
        "Anwalt_Grund": (4, "communications[0]", "rechtsbeistand"),
        "Anwalt_Wunsch": (4, "suisseIDLastName[0]", "rechtsbeistand"),
        "Rechtsschutz_Besteht": (4, "RadioButtonList[0]", "rechtsschutz"),
        "Rechtsschutz_Umfang": (4, "amount[0]", "rechtsschutz"),
        "Anwalt_Vorschuss": (4, "paymentinadvance[0]", "rechtsschutz"),
        "Sozialhilfe_Bezug": (4, "RadioButtonList[0]", "sozialhilfe"),
        "Sozialhilfe_Zeitspanne": (4, "von[0]", "sozialhilfe"),

        # Page 6 (Index 5): Finances (Income: auslage[0].Table1[0] & Expenses: rechtsbegehren[0].Table1[0])
        "Einkommen_Nettolohn": (5, "Cell2[0]", "auslage[0].Table1[0].Row1[0]"),
        "Einkommen_ALV": (5, "Cell2[0]", "auslage[0].Table1[0].Row4[0]"),
        "Einkommen_Total": (5, "Cell2[0]", "auslage[0].Table1[0].Row11[0]"),
        "Einkommen_Partner": (5, "Cell3[0]", "auslage[0].Table1[0].Row11[0]"),
        "Auslagen_Mietzins": (5, "Cell2[0]", "rechtsbegehren[0].Table1[0].Row1[0]"),
        "Auslagen_Hypothekarzins": (5, "Cell2[0]", "rechtsbegehren[0].Table1[0].Row2[0]"),
        "Auslagen_Krankenkasse": (5, "Cell2[0]", "rechtsbegehren[0].Table1[0].Row3[0]"),
        "Auslagen_Versicherungen": (5, "Cell2[0]", "rechtsbegehren[0].Table1[0].Row4[0]"),
        "Auslagen_Alimente": (5, "Cell2[0]", "rechtsbegehren[0].Table1[0].Row16[0]"),
        "Auslagen_Kind_Direkt": (5, "Cell2[0]", "rechtsbegehren[0].Table1[0].Row14[0]"),
        "Auslagen_Total": (5, "Cell2[0]", "rechtsbegehren[0].Table1[0].Row23[0]"),

        # Page 7 (Index 6): Section 13 Bevorstehende Auslagen & Section 14 Vermögen
        "Bevorstehende_Auslagen": (6, "communications[0]", "page7[0]"),
        "Konti_Saldi": (6, "Cell1[0]", "vermögen[0].Table1[0].Row1[0]"),
        "Vermoegen_Konti_Bez1": (6, "Cell1[0]", "vermögen[0].Table1[0].Row1[0]"),
        "Vermoegen_Konti_Betrag1": (6, "Cell2[0]", "vermögen[0].Table1[0].Row1[0]"),
        "Vermoegen_Bargeld_Bez": (6, "Cell1[0]", "vermögen[0].Table1[0].Row4[0]"),
        "Vermoegen_Bargeld_Betrag": (6, "Cell2[0]", "vermögen[0].Table1[0].Row4[0]"),
        "Liegenschaft_Steinhausen": (6, "Cell1[0]", "vermögen[0].Table1[0].Row5[0]"),
        "Vermoegen_Liegenschaft_Bez": (6, "Cell1[0]", "vermögen[0].Table1[0].Row5[0]"),
        "Vermoegen_Liegenschaft_Bez1": (6, "Cell1[0]", "vermögen[0].Table1[0].Row5[0]"),
        "Vermoegen_Liegenschaft_Wert1": (6, "Cell2[0]", "vermögen[0].Table1[0].Row5[0]"),
        "Vermoegen_Liegenschaft_Eigentum": (6, "Cell1[0]", "vermögen[0].Table1[0].Row6[0]"),
        "Vermoegen_Liegenschaft_Bez2": (6, "Cell1[0]", "vermögen[0].Table1[0].Row6[0]"),
        "Vermoegen_Liegenschaft_Wert2": (6, "Cell2[0]", "vermögen[0].Table1[0].Row6[0]"),
        "Vermoegen_Liegenschaft_Bez_Total": (6, "Cell1[0]", "vermögen[0].Table1[0].Row7[0]"),
        "Vermoegen_Liegenschaft_Wert": (6, "Cell2[0]", "vermögen[0].Table1[0].Row7[0]"),
        "Vermoegen_Fahrzeug_Bez": (6, "Cell1[0]", "vermögen[0].Table1[0].Row8[0]"),
        "Vermoegen_Fahrzeug_Wert": (6, "Cell2[0]", "vermögen[0].Table1[0].Row8[0]"),
        "Vermoegen_Fahrzeug_Typ": (6, "Cell1[0]", "vermögen[0].Table1[0].Row9[0]"),
        "Vermoegen_Lebensversicherung_Bez": (6, "Cell1[0]", "vermögen[0].Table1[0].Row12[0]"),
        "Vermoegen_Lebensversicherung_Wert": (6, "Cell2[0]", "vermögen[0].Table1[0].Row13[0]"),
        "Vermoegen_Weiteres_Bez": (6, "Cell1[0]", "vermögen[0].Table1[0].Row14[0]"),
        "Vermoegen_Weiteres_Betrag": (6, "Cell2[0]", "vermögen[0].Table1[0].Row14[0]"),
        "Vermoegen_Total": (6, "Cell2[0]", "vermögen[0].Table1[0].Row19[0]"),
        "Vermoegen_Total_Partner": (6, "Cell3[0]", "vermögen[0].Table1[0].Row19[0]"),

        # Page 8 (Index 7): Section 15 Schulden
        "Grundpfandschuld_Steinhausen": (7, "Cell2[0]", "rechtsbegehren[0].Table1[0].Row14[0]"),
        "Schulden_Kredit_Glaeubiger1": (7, "Cell2[0]", "rechtsbegehren[0].Table1[0].Row1[0]"),
        "Schulden_Kredit_Betrag1": (7, "Cell2[0]", "rechtsbegehren[0].Table1[0].Row2[0]"),
        "Schulden_Kredit_Glaeubiger2": (7, "Cell2[0]", "rechtsbegehren[0].Table1[0].Row3[0]"),
        "Schulden_Kredit_Betrag2": (7, "Cell2[0]", "rechtsbegehren[0].Table1[0].Row4[0]"),
        "Schulden_Kredite_Total": (7, "Cell2[0]", "rechtsbegehren[0].Table1[0].Row7[0]"),
        "Schulden_Steuern_Jahr1": (7, "Cell2[0]", "rechtsbegehren[0].Table1[0].Row8[0]"),
        "Schulden_Steuern_Betrag1": (7, "Cell2[0]", "rechtsbegehren[0].Table1[0].Row9[0]"),
        "Schulden_Steuern_Jahr2": (7, "Cell2[0]", "rechtsbegehren[0].Table1[0].Row10[0]"),
        "Schulden_Steuern_Betrag2": (7, "Cell2[0]", "rechtsbegehren[0].Table1[0].Row11[0]"),
        "Schulden_Grundpfand": (7, "Cell2[0]", "rechtsbegehren[0].Table1[0].Row14[0]"),
        "Schulden_Weitere_Bez": (7, "Cell2[0]", "rechtsbegehren[0].Table1[0].Row15[0]"),
        "Schulden_Weitere_Betrag": (7, "Cell2[0]", "rechtsbegehren[0].Table1[0].Row16[0]"),
        "Schulden_Total": (7, "Cell2[0]", "rechtsbegehren[0].Table1[0].Row17[0]"),
        "Schulden_Total_Partner": (7, "Cell3[0]", "rechtsbegehren[0].Table1[0].Row17[0]"),

        # Page 9 (Index 8): Documents / Beilagen
        "weitere Urkunden, welche die finanzielle Situation der gesuchstellenden Partei belegen:": (8, "communications[0]", "beilagen"),
    }

    def __init__(self, reader: PdfReader):
        self.reader = reader
        self.all_fields: Dict[str, Any] = reader.get_fields() or {}
        self.page_field_map: Dict[int, List[str]] = self._index_fields_by_page()

    def _index_fields_by_page(self) -> Dict[int, List[str]]:
        """Indexes every field key to its corresponding PDF page index."""
        indexed: Dict[int, List[str]] = {i: [] for i in range(len(self.reader.pages))}

        for full_key in self.all_fields.keys():
            # Check for page indicator in field name e.g. .page1[0] -> index 0
            matched_page = None
            for p_idx in range(1, 11):
                if f".page{p_idx}[" in full_key or f"page{p_idx}." in full_key:
                    matched_page = p_idx - 1
                    break

            if matched_page is not None and matched_page < len(self.reader.pages):
                indexed[matched_page].append(full_key)
            else:
                # Fallback: register across all pages if not strictly segmented
                for p_idx in indexed.keys():
                    indexed[p_idx].append(full_key)

        return indexed

    def resolve(self, alias: str, val: str) -> Optional[Tuple[int, str]]:
        """
        Resolves a friendly alias to (page_index, fully_qualified_pdf_field_name).
        """
        # 1. Exact match check against all keys
        if alias in self.all_fields:
            # find its page
            for p_idx, fields in self.page_field_map.items():
                if alias in fields:
                    return (p_idx, alias)
            return (0, alias)

        # 2. Canonical target mapping
        if alias in self.CANONICAL_TARGETS:
            page_idx, leaf_target, parent_filter = self.CANONICAL_TARGETS[alias]
            candidates = self.page_field_map.get(page_idx, [])

            for c in candidates:
                if c.endswith(leaf_target):
                    if parent_filter is None or parent_filter in c:
                        return (page_idx, c)

        # 3. Fuzzy leaf match across pages
        for p_idx, fields in self.page_field_map.items():
            for c in fields:
                if c.endswith(f".{alias}") or c == alias:
                    return (p_idx, c)

        return None


# =============================================================================
# PDF Form Engine (Core Orchestrator)
# =============================================================================

class PDFFormFiller:
    """
    Enterprise-grade PDF Form Filling Engine.
    Executes field mapping, validation, population, and atomic persistence.
    """

    def __init__(self, template_path: Path, output_path: Path):
        self.template_path = Path(template_path).resolve()
        self.output_path = Path(output_path).resolve()
        self._validate_template()

    def _validate_template(self) -> None:
        """Verifies template existence and AcroForm structure."""
        if not self.template_path.exists():
            raise SourceFileNotFoundError(f"Input PDF template does not exist: {self.template_path}")
        if not self.template_path.is_file():
            raise SourceFileNotFoundError(f"Input path is not a valid file: {self.template_path}")

        try:
            reader = PdfReader(str(self.template_path))
            if len(reader.pages) == 0:
                raise InvalidPDFError("PDF contains zero pages.")
            fields = reader.get_fields()
            if not fields:
                ConsoleUI.warning("No interactive AcroForm fields detected in PDF.")
        except Exception as e:
            if isinstance(e, PDFFormError):
                raise
            raise InvalidPDFError(f"Failed to parse PDF document: {e}") from e

    def inspect_schema(self) -> None:
        """Inspects and visualizes the PDF AcroForm hierarchy."""
        reader = PdfReader(str(self.template_path))
        fields = reader.get_fields() or {}

        tree = Tree(f"[bold cyan]PDF Form Hierarchy[/] ([magenta]{len(fields)} fields[/])")
        pages: Dict[str, List[Tuple[str, str, str]]] = {}

        for k, v in fields.items():
            if not v.get("/FT"):
                continue
            parts = k.split(".")
            page_token = next((p for p in parts if "page" in p), "Global")
            tu = str(v.get("/TU", ""))
            ft = str(v.get("/FT", "Txt"))
            pages.setdefault(page_token, []).append((parts[-1], tu, ft))

        for p_name, f_list in sorted(pages.items()):
            branch = tree.add(f"[bold yellow]{p_name}[/] ({len(f_list)} fields)")
            for leaf, tu, ft in f_list[:12]:
                label = f"[white]{leaf}[/] [muted]({ft})[/]"
                if tu:
                    label += f" -> [green]'{tu}'[/]"
                branch.add(label)
            if len(f_list) > 12:
                branch.add(f"[dim]... and {len(f_list) - 12} more fields[/]")

        console.print(tree)

    def populate(
        self,
        payload: UPFormPayload,
        dry_run: bool = False,
        verbose: bool = True,
    ) -> Tuple[int, int]:
        """
        Populates the PDF using atomic write semantics.
        Returns: (matched_fields_count, skipped_fields_count)
        """
        start_time = time.perf_counter()
        reader = PdfReader(str(self.template_path))
        resolver = AcroFieldResolver(reader)
        writer = PdfWriter()
        writer.append(reader)

        alias_data = payload.to_alias_dict()
        page_updates: Dict[int, Dict[str, str]] = {i: {} for i in range(len(writer.pages))}
        records: List[Dict[str, Any]] = []

        matched_count = 0
        skipped_count = 0

        # Phase 1: Resolve all inputs to concrete PDF targets
        for alias, val in alias_data.items():
            resolved = resolver.resolve(alias, str(val))
            if resolved:
                p_idx, target_field = resolved
                page_updates[p_idx][target_field] = normalize_field_value(target_field, val)
                matched_count += 1
                records.append({
                    "alias": alias,
                    "target_field": target_field,
                    "page_index": p_idx + 1,
                    "value": val,
                    "matched": True,
                })
            else:
                skipped_count += 1
                records.append({
                    "alias": alias,
                    "target_field": "None (Unresolved)",
                    "page_index": "-",
                    "value": val,
                    "matched": False,
                })

        # Phase 2: Render audit table
        if verbose:
            ConsoleUI.render_field_table(records)

        if dry_run:
            ConsoleUI.warning("Dry-run requested: skipping file write.")
            return matched_count, skipped_count

        # Phase 3: Update page form fields
        for p_idx, field_dict in page_updates.items():
            if field_dict and p_idx < len(writer.pages):
                writer.update_page_form_field_values(writer.pages[p_idx], field_dict)

        # Phase 4: Atomic write out
        with AtomicFileWriter(self.output_path) as temp_target:
            with open(temp_target, "wb") as f_out:
                writer.write(f_out)

        elapsed = time.perf_counter() - start_time
        file_size_kb = self.output_path.stat().st_size / 1024

        ConsoleUI.success(
            f"Successfully compiled form to: [bold underline]{self.output_path}[/] "
            f"({file_size_kb:.1f} KB in {elapsed:.2f}s)"
        )

        return matched_count, skipped_count


# =============================================================================
# CLI Entry Point
# =============================================================================

def parse_args() -> argparse.Namespace:
    default_input = r"C:\Users\titwa\Downloads\Gesuch UP elektronisch ausfüllbar.pdf"
    default_output = r"C:\Users\titwa\Downloads\Gesuch_UP_Falempin_Rempli.pdf"

    parser = argparse.ArgumentParser(
        description="Professional-grade Cantonal Legal Aid Form Filler (Art. 119 ZPO).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i", "--input",
        type=Path,
        default=Path(default_input),
        help="Path to the official fillable input PDF template",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=Path(default_output),
        help="Path where the filled output PDF should be atomically written",
    )
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Inspect and print the AcroForm schema without modifying files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute field mapping and resolution without writing to disk",
    )
    parser.add_argument(
        "-d", "--data-file",
        type=Path,
        default=None,
        help="Optional JSON file containing form overrides",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress detailed table rendering",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    ConsoleUI.banner(
        "Kanton Zug • Gesuch um unentgeltliche Rechtspflege (Art. 119 ZPO)",
        "Automatisierte Formularausfüllung mit atomarer Speicherung & Schema-Auflösung",
    )

    try:
        filler = PDFFormFiller(args.input, args.output)

        if args.inspect:
            filler.inspect_schema()
            return 0

        # Load payload and optional JSON overrides
        payload = UPFormPayload()
        data_to_load = args.data_file
        if not data_to_load:
            default_data = Path(__file__).parent / "donnees.json"
            if default_data.exists():
                data_to_load = default_data

        if data_to_load:
            if not data_to_load.exists():
                raise FormValidationError(f"Provided data file does not exist: {data_to_load}")
            with open(data_to_load, "r", encoding="utf-8") as f:
                overrides = json.load(f)
                payload.raw_overrides.update(overrides)
            ConsoleUI.info(f"Loaded {len(overrides)} custom data overrides from {data_to_load}")

        # Execute
        matched, skipped = filler.populate(
            payload=payload,
            dry_run=args.dry_run,
            verbose=not args.quiet,
        )

        ConsoleUI.info(f"Summary: [bold green]{matched} matched[/] | [bold yellow]{skipped} skipped[/]")
        return 0

    except PDFFormError as e:
        ConsoleUI.error(str(e))
        return 1
    except Exception as e:
        ConsoleUI.error(f"Unexpected operational failure: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())