#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
Formular-Assistent : Générateur de mapping & injecteur de données PDF
=============================================================================
Ce script :
  1. Extrait et exporte mapping.json (correspondances alias -> chemins PDF).
  2. Injecte les données (depuis donnees.json) en utilisant ce mapping direct.
  3. Effectue une persistance atomique du fichier PDF généré.
=============================================================================
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    print("[ERREUR] 'pypdf' n'est pas installé. Exécutez : pip install pypdf", file=sys.stderr)
    sys.exit(1)

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    console = Console()
except ImportError:
    console = None


# Définition par défaut du catalogue de correspondances (alias -> structure)
CANONICAL_MAPPINGS: List[Dict[str, Any]] = [
    # Page 1 (index 0): Klagende Partei (Applicant)
    {"alias": "Name", "page_index": 0, "page_label": "page1[0]", "target_field_leaf": "suisseIDLastName[0]", "parent_group": "klagendePartei",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page1[0].Header[0].klagendePartei[0].suisseIDLastName[0]"},
    {"alias": "Vorname", "page_index": 0, "page_label": "page1[0]", "target_field_leaf": "suisseIDFirstName[0]", "parent_group": "klagendePartei",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page1[0].Header[0].klagendePartei[0].suisseIDFirstName[0]"},
    {"alias": "Strasse", "page_index": 0, "page_label": "page1[0]", "target_field_leaf": "street[0]", "parent_group": "klagendePartei",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page1[0].Header[0].klagendePartei[0].street[0]"},
    {"alias": "Hausnummer", "page_index": 0, "page_label": "page1[0]", "target_field_leaf": "houseNumber[0]", "parent_group": "klagendePartei",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page1[0].Header[0].klagendePartei[0].houseNumber[0]"},
    {"alias": "PLZ", "page_index": 0, "page_label": "page1[0]", "target_field_leaf": "swissZipCode[0]", "parent_group": "klagendePartei",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page1[0].Header[0].klagendePartei[0].swissZipCode[0]"},
    {"alias": "Ort", "page_index": 0, "page_label": "page1[0]", "target_field_leaf": "municipalityName[0]", "parent_group": "klagendePartei",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page1[0].Header[0].klagendePartei[0].municipalityName[0]"},
    {"alias": "Telefon", "page_index": 0, "page_label": "page1[0]", "target_field_leaf": "phoneNumber[0]", "parent_group": "klagendePartei",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page1[0].Header[0].klagendePartei[0].phoneNumber[0]"},
    {"alias": "Mobil", "page_index": 0, "page_label": "page1[0]", "target_field_leaf": "phoneNumberMobile[0]", "parent_group": "klagendePartei",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page1[0].Header[0].klagendePartei[0].phoneNumberMobile[0]"},
    {"alias": "Email", "page_index": 0, "page_label": "page1[0]", "target_field_leaf": "eCHformUserEmail[0]", "parent_group": "klagendePartei",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page1[0].Header[0].klagendePartei[0].eCHformUserEmail[0]"},
    {"alias": "Sprache", "page_index": 0, "page_label": "page1[0]", "target_field_leaf": "language[0]", "parent_group": "klagendePartei",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page1[0].Header[0].klagendePartei[0].language[0]"},
    {"alias": "Uebersetzer_erforderlich", "page_index": 0, "page_label": "page1[0]", "target_field_leaf": "requireTranslation[0]", "parent_group": "klagendePartei",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page1[0].Header[0].klagendePartei[0].requireTranslation[0]"},
    {"alias": "Geburtsdatum", "page_index": 0, "page_label": "page1[0]", "target_field_leaf": "suisseIDDateOfBirth[0]", "parent_group": "klagendePartei",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page1[0].Header[0].klagendePartei[0].suisseIDDateOfBirth[0]"},
    {"alias": "Beruf", "page_index": 0, "page_label": "page1[0]", "target_field_leaf": "profession[0]", "parent_group": "klagendePartei",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page1[0].Header[0].klagendePartei[0].profession[0]"},
    {"alias": "Heimatort", "page_index": 0, "page_label": "page1[0]", "target_field_leaf": "suisseIDPlaceOfBirth[0]", "parent_group": "klagendePartei",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page1[0].Header[0].klagendePartei[0].suisseIDPlaceOfBirth[0]"},
    {"alias": "Nationalitaet", "page_index": 0, "page_label": "page1[0]", "target_field_leaf": "suisseIDOrigin[0]", "parent_group": "klagendePartei",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page1[0].Header[0].klagendePartei[0].suisseIDOrigin[0]"},
    {"alias": "Zivilstand", "page_index": 0, "page_label": "page1[0]", "target_field_leaf": "maritalStatus[0]", "parent_group": "klagendePartei",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page1[0].Header[0].klagendePartei[0].maritalStatus[0]"},

    # Page 2 (index 1): Partner (Section 2)
    {"alias": "Ehepartner_Name", "page_index": 1, "page_label": "page2[0]", "target_field_leaf": "suisseIDLastName[0]", "parent_group": "partner",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page2[0].partner[0].suisseIDLastName[0]"},
    {"alias": "Ehepartner_Vorname", "page_index": 1, "page_label": "page2[0]", "target_field_leaf": "suisseIDFirstName[0]", "parent_group": "partner",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page2[0].partner[0].suisseIDFirstName[0]"},
    {"alias": "Ehepartner_Strasse", "page_index": 1, "page_label": "page2[0]", "target_field_leaf": "street[0]", "parent_group": "partner",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page2[0].partner[0].street[0]"},
    {"alias": "Ehepartner_Hausnummer", "page_index": 1, "page_label": "page2[0]", "target_field_leaf": "houseNumber[0]", "parent_group": "partner",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page2[0].partner[0].houseNumber[0]"},
    {"alias": "Ehepartner_Ort", "page_index": 1, "page_label": "page2[0]", "target_field_leaf": "municipalityName[0]", "parent_group": "partner",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page2[0].partner[0].municipalityName[0]"},
    {"alias": "Ehepartner_PLZ", "page_index": 1, "page_label": "page2[0]", "target_field_leaf": "swissZipCode[0]", "parent_group": "partner",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page2[0].partner[0].swissZipCode[0]"},
    {"alias": "Ehepartner_Telefon", "page_index": 1, "page_label": "page2[0]", "target_field_leaf": "phoneNumber[0]", "parent_group": "partner",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page2[0].partner[0].phoneNumber[0]"},
    {"alias": "Ehepartner_Mobil", "page_index": 1, "page_label": "page2[0]", "target_field_leaf": "phoneNumberMobile[0]", "parent_group": "partner",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page2[0].partner[0].phoneNumberMobile[0]"},
    {"alias": "Ehepartner_Email", "page_index": 1, "page_label": "page2[0]", "target_field_leaf": "eCHformUserEmail[0]", "parent_group": "partner",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page2[0].partner[0].eCHformUserEmail[0]"},
    {"alias": "Ehepartner_Geburtsdatum", "page_index": 1, "page_label": "page2[0]", "target_field_leaf": "suisseIDDateOfBirth[0]", "parent_group": "partner",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page2[0].partner[0].suisseIDDateOfBirth[0]"},
    {"alias": "Ehepartner_Beruf", "page_index": 1, "page_label": "page2[0]", "target_field_leaf": "profession[0]", "parent_group": "partner",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page2[0].partner[0].profession[0]"},
    {"alias": "Ehepartner_Heimatort", "page_index": 1, "page_label": "page2[0]", "target_field_leaf": "suisseIDPlaceOfBirth[0]", "parent_group": "partner",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page2[0].partner[0].suisseIDPlaceOfBirth[0]"},
    {"alias": "Ehepartner_Nationalitaet", "page_index": 1, "page_label": "page2[0]", "target_field_leaf": "suisseIDOrigin[0]", "parent_group": "partner",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page2[0].partner[0].suisseIDOrigin[0]"},
    {"alias": "Ehepartner_Arbeitgeber", "page_index": 1, "page_label": "page2[0]", "target_field_leaf": "profession[1]", "parent_group": "partner",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page2[0].partner[0].profession[1]"},

    # Page 2 (index 1): Eigene Kinder (Section 3: Child 1 - Aloïs Madiba)
    {"alias": "Kind1_Name", "page_index": 1, "page_label": "page2[0]", "target_field_leaf": "suisseIDLastName[0]", "parent_group": "eigeneKinder",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page2[0].eigeneKinder[0].suisseIDLastName[0]"},
    {"alias": "Kind1_Vorname", "page_index": 1, "page_label": "page2[0]", "target_field_leaf": "suisseIDFirstName[0]", "parent_group": "eigeneKinder",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page2[0].eigeneKinder[0].suisseIDFirstName[0]"},
    {"alias": "Kind1_Geburtsdatum", "page_index": 1, "page_label": "page2[0]", "target_field_leaf": "suisseIDDateOfBirth[0]", "parent_group": "eigeneKinder",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page2[0].eigeneKinder[0].suisseIDDateOfBirth[0]"},
    {"alias": "Kind1_Haushalt", "page_index": 1, "page_label": "page2[0]", "target_field_leaf": "RadioButtonList[0]", "parent_group": "eigeneKinder",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page2[0].eigeneKinder[0].RadioButtonList[0]"},

    # Page 3 (index 2): Kinder der Partnerin (Section 4: Child 1 - Hikari, Child 2 - Hiro)
    {"alias": "PartnerKind1_Name", "page_index": 2, "page_label": "page3[0]", "target_field_leaf": "suisseIDLastName[0]", "parent_group": "eigeneKinder",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page3[0].eigeneKinder[0].suisseIDLastName[0]"},
    {"alias": "PartnerKind1_Vorname", "page_index": 2, "page_label": "page3[0]", "target_field_leaf": "suisseIDFirstName[0]", "parent_group": "eigeneKinder",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page3[0].eigeneKinder[0].suisseIDFirstName[0]"},
    {"alias": "PartnerKind1_Geburtsdatum", "page_index": 2, "page_label": "page3[0]", "target_field_leaf": "suisseIDDateOfBirth[0]", "parent_group": "eigeneKinder",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page3[0].eigeneKinder[0].suisseIDDateOfBirth[0]"},
    {"alias": "PartnerKind1_Haushalt", "page_index": 2, "page_label": "page3[0]", "target_field_leaf": "RadioButtonList[0]", "parent_group": "eigeneKinder",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page3[0].eigeneKinder[0].RadioButtonList[0]"},
    {"alias": "PartnerKind2_Name", "page_index": 2, "page_label": "page3[0]", "target_field_leaf": "suisseIDLastName[1]", "parent_group": "eigeneKinder",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page3[0].eigeneKinder[0].suisseIDLastName[1]"},
    {"alias": "PartnerKind2_Vorname", "page_index": 2, "page_label": "page3[0]", "target_field_leaf": "suisseIDFirstName[1]", "parent_group": "eigeneKinder",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page3[0].eigeneKinder[0].suisseIDFirstName[1]"},
    {"alias": "PartnerKind2_Geburtsdatum", "page_index": 2, "page_label": "page3[0]", "target_field_leaf": "suisseIDDateOfBirth[1]", "parent_group": "eigeneKinder",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page3[0].eigeneKinder[0].suisseIDDateOfBirth[1]"},
    {"alias": "PartnerKind2_Haushalt", "page_index": 2, "page_label": "page3[0]", "target_field_leaf": "RadioButtonList[1]", "parent_group": "eigeneKinder",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page3[0].eigeneKinder[0].RadioButtonList[1]"},

    # Page 4 (index 3): Section 5 Andere Personen im Haushalt & Section 6 Rechtsbegehren
    {"alias": "WeiterePersonen_Haushalt", "page_index": 3, "page_label": "page4[0]", "target_field_leaf": "suisseIDLastName[0]", "parent_group": "eigeneKinder",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page4[0].eigeneKinder[0].suisseIDLastName[0]"},
    {"alias": "Hauptsache_Rechtsbegehren", "page_index": 3, "page_label": "page4[0]", "target_field_leaf": "communications[0]", "parent_group": "rechtsbegehren",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page4[0].rechtsbegehren[0].communications[0]"},

    # Page 5 (index 4): Section 7 Begründung & Section 8 Unentgeltlicher Rechtsbeistand & Section 9 Rechtsschutz & Section 10 Sozialhilfe
    {"alias": "Hauptsache_Begruendung", "page_index": 4, "page_label": "page5[0]", "target_field_leaf": "communications[0]", "parent_group": "Streitgegenstand",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page5[0].Streitgegenstand[0].communications[0]"},
    {"alias": "Anwalt_Benoetigt", "page_index": 4, "page_label": "page5[0]", "target_field_leaf": "RadioButtonList[0]", "parent_group": "rechtsbeistand",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page5[0].rechtsbeistand[0].RadioButtonList[0]"},
    {"alias": "Anwalt_Grund", "page_index": 4, "page_label": "page5[0]", "target_field_leaf": "communications[0]", "parent_group": "rechtsbeistand",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page5[0].rechtsbeistand[0].communications[0]"},
    {"alias": "Anwalt_Wunsch", "page_index": 4, "page_label": "page5[0]", "target_field_leaf": "suisseIDLastName[0]", "parent_group": "rechtsbeistand",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page5[0].rechtsbeistand[0].suisseIDLastName[0]"},
    {"alias": "Rechtsschutz_Besteht", "page_index": 4, "page_label": "page5[0]", "target_field_leaf": "RadioButtonList[0]", "parent_group": "rechtsschutz",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page5[0].rechtsschutz[0].RadioButtonList[0]"},
    {"alias": "Rechtsschutz_Umfang", "page_index": 4, "page_label": "page5[0]", "target_field_leaf": "amount[0]", "parent_group": "rechtsschutz",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page5[0].rechtsschutz[0].amount[0]"},
    {"alias": "Anwalt_Vorschuss", "page_index": 4, "page_label": "page5[0]", "target_field_leaf": "paymentinadvance[0]", "parent_group": "rechtsschutz",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page5[0].rechtsschutz[0].paymentinadvance[0]"},
    {"alias": "Sozialhilfe_Bezug", "page_index": 4, "page_label": "page5[0]", "target_field_leaf": "RadioButtonList[0]", "parent_group": "sozialhilfe",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page5[0].sozialhilfe[0].RadioButtonList[0]"},
    {"alias": "Sozialhilfe_Zeitspanne", "page_index": 4, "page_label": "page5[0]", "target_field_leaf": "von[0]", "parent_group": "sozialhilfe",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page5[0].sozialhilfe[0].von[0]"},

    # Page 6 (index 5): Section 11 Einkommen (auslage[0].Table1[0]) & Section 12 Auslagen (rechtsbegehren[0].Table1[0])
    {"alias": "Einkommen_Nettolohn", "page_index": 5, "page_label": "page6[0]", "target_field_leaf": "Cell2[0]", "parent_group": "auslage[0].Row1[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page6[0].auslage[0].Table1[0].Row1[0].Cell2[0]"},
    {"alias": "Einkommen_Nettolohn_Partner", "page_index": 5, "page_label": "page6[0]", "target_field_leaf": "Cell3[0]", "parent_group": "auslage[0].Row1[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page6[0].auslage[0].Table1[0].Row1[0].Cell3[0]"},
    {"alias": "Einkommen_Nebenerwerb", "page_index": 5, "page_label": "page6[0]", "target_field_leaf": "Cell2[0]", "parent_group": "auslage[0].Row2[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page6[0].auslage[0].Table1[0].Row2[0].Cell2[0]"},
    {"alias": "Einkommen_Renten", "page_index": 5, "page_label": "page6[0]", "target_field_leaf": "Cell2[0]", "parent_group": "auslage[0].Row3[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page6[0].auslage[0].Table1[0].Row3[0].Cell2[0]"},
    {"alias": "Einkommen_ALV", "page_index": 5, "page_label": "page6[0]", "target_field_leaf": "Cell2[0]", "parent_group": "auslage[0].Row4[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page6[0].auslage[0].Table1[0].Row4[0].Cell2[0]"},
    {"alias": "Einkommen_Unterhalt", "page_index": 5, "page_label": "page6[0]", "target_field_leaf": "Cell2[0]", "parent_group": "auslage[0].Row5[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page6[0].auslage[0].Table1[0].Row5[0].Cell2[0]"},
    {"alias": "Einkommen_Familienzulagen", "page_index": 5, "page_label": "page6[0]", "target_field_leaf": "Cell2[0]", "parent_group": "auslage[0].Row7[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page6[0].auslage[0].Table1[0].Row7[0].Cell2[0]"},
    {"alias": "Einkommen_Total", "page_index": 5, "page_label": "page6[0]", "target_field_leaf": "Cell2[0]", "parent_group": "auslage[0].Row11[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page6[0].auslage[0].Table1[0].Row11[0].Cell2[0]"},
    {"alias": "Einkommen_Partner", "page_index": 5, "page_label": "page6[0]", "target_field_leaf": "Cell3[0]", "parent_group": "auslage[0].Row11[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page6[0].auslage[0].Table1[0].Row11[0].Cell3[0]"},

    {"alias": "Auslagen_Mietzins", "page_index": 5, "page_label": "page6[0]", "target_field_leaf": "Cell2[0]", "parent_group": "rechtsbegehren[0].Row1[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page6[0].rechtsbegehren[0].Table1[0].Row1[0].Cell2[0]"},
    {"alias": "Auslagen_Hypothekarzins", "page_index": 5, "page_label": "page6[0]", "target_field_leaf": "Cell2[0]", "parent_group": "rechtsbegehren[0].Row2[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page6[0].rechtsbegehren[0].Table1[0].Row2[0].Cell2[0]"},
    {"alias": "Auslagen_Krankenkasse", "page_index": 5, "page_label": "page6[0]", "target_field_leaf": "Cell2[0]", "parent_group": "rechtsbegehren[0].Row3[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page6[0].rechtsbegehren[0].Table1[0].Row3[0].Cell2[0]"},
    {"alias": "Auslagen_Versicherungen", "page_index": 5, "page_label": "page6[0]", "target_field_leaf": "Cell2[0]", "parent_group": "rechtsbegehren[0].Row4[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page6[0].rechtsbegehren[0].Table1[0].Row4[0].Cell2[0]"},
    {"alias": "Auslagen_Kind_Direkt", "page_index": 5, "page_label": "page6[0]", "target_field_leaf": "Cell2[0]", "parent_group": "rechtsbegehren[0].Row14[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page6[0].rechtsbegehren[0].Table1[0].Row14[0].Cell2[0]"},
    {"alias": "Auslagen_Alimente", "page_index": 5, "page_label": "page6[0]", "target_field_leaf": "Cell2[0]", "parent_group": "rechtsbegehren[0].Row16[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page6[0].rechtsbegehren[0].Table1[0].Row16[0].Cell2[0]"},
    {"alias": "Auslagen_Total", "page_index": 5, "page_label": "page6[0]", "target_field_leaf": "Cell2[0]", "parent_group": "rechtsbegehren[0].Row23[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page6[0].rechtsbegehren[0].Table1[0].Row23[0].Cell2[0]"},
    {"alias": "Auslagen_Total_Partner", "page_index": 5, "page_label": "page6[0]", "target_field_leaf": "Cell3[0]", "parent_group": "rechtsbegehren[0].Row23[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page6[0].rechtsbegehren[0].Table1[0].Row23[0].Cell3[0]"},

    # Page 7 (index 6): Section 13 Bevorstehende grössere Auslagen
    {"alias": "Bevorstehende_Auslagen", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "communications[0]", "parent_group": "page7[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].communications[0]"},

    # Page 7 (index 6): Section 14 Vermögen (vermögen[0].Table1[0])
    {"alias": "Konti_Saldi", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell1[0]", "parent_group": "vermögen[0].Row1[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row1[0].Cell1[0]"},
    {"alias": "Vermoegen_Konti_Bez1", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell1[0]", "parent_group": "vermögen[0].Row1[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row1[0].Cell1[0]"},
    {"alias": "Vermoegen_Konti_Betrag1", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell2[0]", "parent_group": "vermögen[0].Row1[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row1[0].Cell2[0]"},
    {"alias": "Vermoegen_Bargeld_Bez", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell1[0]", "parent_group": "vermögen[0].Row4[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row4[0].Cell1[0]"},
    {"alias": "Vermoegen_Bargeld_Betrag", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell2[0]", "parent_group": "vermögen[0].Row4[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row4[0].Cell2[0]"},
    {"alias": "Liegenschaft_Steinhausen", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell1[0]", "parent_group": "vermögen[0].Row5[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row5[0].Cell1[0]"},
    {"alias": "Vermoegen_Liegenschaft_Bez", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell1[0]", "parent_group": "vermögen[0].Row5[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row5[0].Cell1[0]"},
    {"alias": "Vermoegen_Liegenschaft_Bez1", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell1[0]", "parent_group": "vermögen[0].Row5[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row5[0].Cell1[0]"},
    {"alias": "Vermoegen_Liegenschaft_Wert1", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell2[0]", "parent_group": "vermögen[0].Row5[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row5[0].Cell2[0]"},
    {"alias": "Vermoegen_Liegenschaft_Eigentum", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell1[0]", "parent_group": "vermögen[0].Row6[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row6[0].Cell1[0]"},
    {"alias": "Vermoegen_Liegenschaft_Bez2", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell1[0]", "parent_group": "vermögen[0].Row6[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row6[0].Cell1[0]"},
    {"alias": "Vermoegen_Liegenschaft_Wert2", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell2[0]", "parent_group": "vermögen[0].Row6[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row6[0].Cell2[0]"},
    {"alias": "Vermoegen_Liegenschaft_Bez_Total", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell1[0]", "parent_group": "vermögen[0].Row7[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row7[0].Cell1[0]"},
    {"alias": "Vermoegen_Liegenschaft_Wert", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell2[0]", "parent_group": "vermögen[0].Row7[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row7[0].Cell2[0]"},
    {"alias": "Vermoegen_Fahrzeug_Bez", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell1[0]", "parent_group": "vermögen[0].Row8[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row8[0].Cell1[0]"},
    {"alias": "Vermoegen_Fahrzeug_Wert", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell2[0]", "parent_group": "vermögen[0].Row8[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row8[0].Cell2[0]"},
    {"alias": "Vermoegen_Fahrzeug_Typ", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell1[0]", "parent_group": "vermögen[0].Row9[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row9[0].Cell1[0]"},
    {"alias": "Vermoegen_Lebensversicherung_Bez", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell1[0]", "parent_group": "vermögen[0].Row12[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row12[0].Cell1[0]"},
    {"alias": "Vermoegen_Lebensversicherung_Wert", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell2[0]", "parent_group": "vermögen[0].Row13[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row13[0].Cell2[0]"},
    {"alias": "Vermoegen_Weiteres_Bez", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell1[0]", "parent_group": "vermögen[0].Row14[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row14[0].Cell1[0]"},
    {"alias": "Vermoegen_Weiteres_Betrag", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell2[0]", "parent_group": "vermögen[0].Row14[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row14[0].Cell2[0]"},
    {"alias": "Vermoegen_Total", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell2[0]", "parent_group": "vermögen[0].Row19[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row19[0].Cell2[0]"},
    {"alias": "Vermoegen_Total_Partner", "page_index": 6, "page_label": "page7[0]", "target_field_leaf": "Cell3[0]", "parent_group": "vermögen[0].Row19[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page7[0].vermögen[0].Table1[0].Row19[0].Cell3[0]"},

    # Page 8 (index 7): Section 15 Schulden (rechtsbegehren[0].Table1[0])
    {"alias": "Schulden_Kredit_Glaeubiger1", "page_index": 7, "page_label": "page8[0]", "target_field_leaf": "Cell2[0]", "parent_group": "rechtsbegehren[0].Row1[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page8[0].rechtsbegehren[0].Table1[0].Row1[0].Cell2[0]"},
    {"alias": "Schulden_Kredit_Betrag1", "page_index": 7, "page_label": "page8[0]", "target_field_leaf": "Cell2[0]", "parent_group": "rechtsbegehren[0].Row2[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page8[0].rechtsbegehren[0].Table1[0].Row2[0].Cell2[0]"},
    {"alias": "Schulden_Kredit_Glaeubiger2", "page_index": 7, "page_label": "page8[0]", "target_field_leaf": "Cell2[0]", "parent_group": "rechtsbegehren[0].Row3[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page8[0].rechtsbegehren[0].Table1[0].Row3[0].Cell2[0]"},
    {"alias": "Schulden_Kredit_Betrag2", "page_index": 7, "page_label": "page8[0]", "target_field_leaf": "Cell2[0]", "parent_group": "rechtsbegehren[0].Row4[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page8[0].rechtsbegehren[0].Table1[0].Row4[0].Cell2[0]"},
    {"alias": "Schulden_Kredite_Total", "page_index": 7, "page_label": "page8[0]", "target_field_leaf": "Cell2[0]", "parent_group": "rechtsbegehren[0].Row7[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page8[0].rechtsbegehren[0].Table1[0].Row7[0].Cell2[0]"},
    {"alias": "Schulden_Steuern_Jahr1", "page_index": 7, "page_label": "page8[0]", "target_field_leaf": "Cell2[0]", "parent_group": "rechtsbegehren[0].Row8[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page8[0].rechtsbegehren[0].Table1[0].Row8[0].Cell2[0]"},
    {"alias": "Schulden_Steuern_Betrag1", "page_index": 7, "page_label": "page8[0]", "target_field_leaf": "Cell2[0]", "parent_group": "rechtsbegehren[0].Row9[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page8[0].rechtsbegehren[0].Table1[0].Row9[0].Cell2[0]"},
    {"alias": "Schulden_Steuern_Jahr2", "page_index": 7, "page_label": "page8[0]", "target_field_leaf": "Cell2[0]", "parent_group": "rechtsbegehren[0].Row10[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page8[0].rechtsbegehren[0].Table1[0].Row10[0].Cell2[0]"},
    {"alias": "Schulden_Steuern_Betrag2", "page_index": 7, "page_label": "page8[0]", "target_field_leaf": "Cell2[0]", "parent_group": "rechtsbegehren[0].Row11[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page8[0].rechtsbegehren[0].Table1[0].Row11[0].Cell2[0]"},
    {"alias": "Grundpfandschuld_Steinhausen", "page_index": 7, "page_label": "page8[0]", "target_field_leaf": "Cell2[0]", "parent_group": "rechtsbegehren[0].Row14[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page8[0].rechtsbegehren[0].Table1[0].Row14[0].Cell2[0]"},
    {"alias": "Schulden_Grundpfand", "page_index": 7, "page_label": "page8[0]", "target_field_leaf": "Cell2[0]", "parent_group": "rechtsbegehren[0].Row14[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page8[0].rechtsbegehren[0].Table1[0].Row14[0].Cell2[0]"},
    {"alias": "Schulden_Weitere_Bez", "page_index": 7, "page_label": "page8[0]", "target_field_leaf": "Cell2[0]", "parent_group": "rechtsbegehren[0].Row15[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page8[0].rechtsbegehren[0].Table1[0].Row15[0].Cell2[0]"},
    {"alias": "Schulden_Weitere_Betrag", "page_index": 7, "page_label": "page8[0]", "target_field_leaf": "Cell2[0]", "parent_group": "rechtsbegehren[0].Row16[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page8[0].rechtsbegehren[0].Table1[0].Row16[0].Cell2[0]"},
    {"alias": "Schulden_Total", "page_index": 7, "page_label": "page8[0]", "target_field_leaf": "Cell2[0]", "parent_group": "rechtsbegehren[0].Row17[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page8[0].rechtsbegehren[0].Table1[0].Row17[0].Cell2[0]"},
    {"alias": "Schulden_Total_Partner", "page_index": 7, "page_label": "page8[0]", "target_field_leaf": "Cell3[0]", "parent_group": "rechtsbegehren[0].Row17[0]",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page8[0].rechtsbegehren[0].Table1[0].Row17[0].Cell3[0]"},

    # Page 9 (index 8): Section 16 Beilagen / Urkunden
    {"alias": "weitere Urkunden, welche die finanzielle Situation der gesuchstellenden Partei belegen:",
     "page_index": 8, "page_label": "page9[0]", "target_field_leaf": "communications[0]", "parent_group": "beilagen",
     "pdf_target_path": "arrivée_personne_nationalité_suisse_établissement[0].page9[0].beilagen[0].communications[0]"}
]


def normalize_field_value(field_name: str, value: Any) -> str:
    """Normalise les valeurs injectées (conversion boutons/cases à cocher/radios)."""
    if value is None:
        return ""
    val_str = str(value).strip()
    if not val_str:
        return ""

    # Case à cocher : übersetzer erforderlich
    if "requireTranslation" in field_name:
        return "/1" if val_str.lower() in ["ja", "oui", "yes", "true", "1"] else "/Off"

    # Radio bouton : zivilstand (marital status)
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

    # RadioButtonList (enfants au même domicile, aide sociale)
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


def write_mapping_json(output_path: Path) -> None:
    """Enregistre le dictionnaire complet de correspondance dans un fichier JSON."""
    data = {
        "description": "Correspondance explicite entre les alias logiques et les champs AcroForm Art. 119 ZPO",
        "mappings": CANONICAL_MAPPINGS
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    if console:
        console.print(f"[bold green]Mapping écrit avec succès dans :[/] {output_path}")
    else:
        print(f"Mapping écrit avec succès dans : {output_path}")


def fill_pdf_from_mapping(
    template_path: Path,
    output_pdf_path: Path,
    mapping_path: Path,
    data_path: Path
) -> None:
    """Remplit le formulaire PDF en exploitant directement le fichier mapping.json."""
    if not template_path.exists():
        raise FileNotFoundError(f"Modèle PDF introuvable : {template_path}")
    if not mapping_path.exists():
        raise FileNotFoundError(f"Fichier mapping introuvable : {mapping_path}")
    if not data_path.exists():
        raise FileNotFoundError(f"Fichier de données introuvable : {data_path}")

    # Chargement des ressources JSON
    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping_data = json.load(f)["mappings"]

    with open(data_path, "r", encoding="utf-8") as f:
        values_data = json.load(f)

    # Création de la table de conversion alias -> (page_index, pdf_target_path)
    lookup = {
        m["alias"]: (m["page_index"], m["pdf_target_path"])
        for m in mapping_data
    }

    reader = PdfReader(str(template_path))
    writer = PdfWriter()
    writer.append(reader)

    page_updates: Dict[int, Dict[str, str]] = {i: {} for i in range(len(writer.pages))}

    # Préparation des injections
    for alias, val in values_data.items():
        if alias in lookup:
            page_idx, target_field = lookup[alias]
            if page_idx < len(writer.pages):
                page_updates[page_idx][target_field] = normalize_field_value(target_field, val)

    # Application aux pages AcroForm
    for page_idx, updates in page_updates.items():
        if updates:
            writer.update_page_form_field_values(writer.pages[page_idx], updates)

    # Écriture atomique sécurisée
    temp_dir = output_pdf_path.parent
    temp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=temp_dir, suffix=".tmp", delete=False) as tmp_file:
        tmp_path = Path(tmp_file.name)
        writer.write(tmp_file)

    os.replace(tmp_path, output_pdf_path)

    if console:
        console.print(f"[bold green]PDF final généré avec succès :[/] {output_pdf_path}")
    else:
        print(f"PDF final généré avec succès : {output_pdf_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gestion et application de mapping.json pour AcroForm.")
    parser.add_argument("--export-mapping", type=Path, default=Path("mapping.json"),
                        help="Chemin de destination pour exporter mapping.json")
    parser.add_argument("--write-pdf", action="store_true",
                        help="Exécute l'injection des données dans le PDF en utilisant le mapping")
    parser.add_argument("-t", "--template", type=Path,
                        default=Path(r"C:\Users\titwa\Downloads\Gesuch UP elektronisch ausfüllbar.pdf"))
    parser.add_argument("-o", "--output", type=Path,
                        default=Path(r"C:\Users\titwa\Downloads\Gesuch_UP_Falempin_Rempli.pdf"))
    parser.add_argument("-m", "--mapping", type=Path, default=Path("mapping.json"))
    parser.add_argument("-d", "--data", type=Path, default=Path("donnees.json"))

    args = parser.parse_args()

    # 1. Génération du mapping.json
    write_mapping_json(args.export_mapping)

    # 2. Remplissage direct si l'option est spécifiée
    if args.write_pdf:
        fill_pdf_from_mapping(
            template_path=args.template,
            output_pdf_path=args.output,
            mapping_path=args.mapping,
            data_path=args.data
        )


if __name__ == "__main__":
    main()