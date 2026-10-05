"""Entity and relationship extraction engine for building the Document Knowledge Graph."""

import re
import json
import time
import logging
from typing import Dict, Any, List, Optional, Tuple, Callable
import httpx
from backend.config import settings
from backend.ai.graph_schemas import (
    EntityNode, EntityEdge, DocumentEntityLink, DocumentKnowledgeGraph,
    THEME_NODE_TYPE, THEME_RELATION,
)

logger = logging.getLogger("graph_extractor")


def canonicalize_node_id(node_type: str, name: str) -> str:
    """Normalize node ID into a clean canonical slug."""
    clean_name = re.sub(r'[^\w\s-]', '', name.strip().lower())
    clean_name = re.sub(r'[-\s]+', '_', clean_name)
    return f"{node_type}_{clean_name}"


# --- Thematic Mindmap: taxonomy root domains as graph hubs -------------------

# category_id -> (parent_id, display_name)
TaxonomyHierarchy = Dict[str, Tuple[Optional[str], str]]

UNCLASSIFIED_THEME_ID = "unclassified"
NON_THEMATIC_DOC_TYPES = {"", "none", "null", "other", "unknown", "unclassified"}


def default_taxonomy_hierarchy() -> TaxonomyHierarchy:
    """Static hierarchy from the seeded DEFAULT_TAXONOMY (used when no DB loader is supplied)."""
    from backend.ai.taxonomy import DEFAULT_TAXONOMY  # lazy: avoid import cycles / DB side effects
    return {c["category_id"]: (c.get("parent_id"), c["name_en"]) for c in DEFAULT_TAXONOMY}


def make_db_taxonomy_loader(conn: Any, lock: Optional[Any] = None) -> Callable[[], TaxonomyHierarchy]:
    """Build a loader reading the live global_taxonomy table (includes LLM-evolved categories)."""
    def _load() -> TaxonomyHierarchy:
        def _query():
            cur = conn.cursor()
            cur.execute("SELECT category_id, parent_id, name_en FROM global_taxonomy;")
            return {r[0]: (r[1], r[2]) for r in cur.fetchall()}
        if lock is not None:
            with lock:
                return _query()
        return _query()
    return _load


class ThemeResolver:
    """Resolves a (leaf) taxonomy doc_type to its root life-domain theme.

    The root of the global_taxonomy parent chain is the theme, e.g.
    lease_contract -> legal_contract -> theme 'theme_legal_contract'.
    """

    def __init__(self,
                 loader: Optional[Callable[[], TaxonomyHierarchy]] = None,
                 ttl_seconds: float = 60.0):
        self._loader = loader
        self._ttl = ttl_seconds
        self._hierarchy: Optional[TaxonomyHierarchy] = None
        self._loaded_at = 0.0

    def _get_hierarchy(self) -> TaxonomyHierarchy:
        now = time.monotonic()
        stale = self._loader is not None and (now - self._loaded_at) > self._ttl
        if self._hierarchy is None or stale:
            loaded: Optional[TaxonomyHierarchy] = None
            if self._loader is not None:
                try:
                    loaded = self._loader()
                except Exception as e:
                    logger.debug(f"Theme taxonomy loader failed, keeping previous hierarchy: {e}")
            if not loaded:
                loaded = self._hierarchy or default_taxonomy_hierarchy()
            self._hierarchy = loaded
            self._loaded_at = now
        return self._hierarchy

    def resolve(self, doc_type: Optional[str]) -> Optional[Tuple[str, str]]:
        """Return (root_category_id, display_name), or None if the doc_type is non-thematic."""
        key = (doc_type or "").strip().lower().replace(" ", "_")
        if key in NON_THEMATIC_DOC_TYPES:
            return None

        hierarchy = self._get_hierarchy()
        if key not in hierarchy:
            return UNCLASSIFIED_THEME_ID, "Unclassified"

        seen = {key}
        while True:
            parent_id, name = hierarchy[key]
            if not parent_id or parent_id not in hierarchy or parent_id in seen:
                return key, name  # root reached (or broken/cyclic chain: stop safely)
            seen.add(parent_id)
            key = parent_id


KNOWN_BANKING_ORGANIZATIONS: Dict[str, Dict[str, Any]] = {
    "organization_zuger_kantonalbank": {
        "name": "Zuger Kantonalbank",
        "aliases": [
            "Zuger Kantonalbank", "Zuger Kantonal Bank", "ZugerKB", "ZGKB",
            "ZKB Zug", "ZKB", "Zuger Kantonalbank AG"
        ],
        "patterns": [
            r"(?i)\b(?:Zuger\s+Kantonalbank(?:\s+AG)?|Zuger\s+Kantonal\s*Bank|ZugerKB|ZGKB)\b",
            r"(?i)\bzugerkb\.ch\b",
            r"(?i)\bCHE-105\.744\.410\b",
            r"(?i)\bCH10\s*0078\s*7\b"
        ],
        "location_id": "location_zug",
        "properties": {
            "aliases": ["Zuger Kantonalbank", "Zuger Kantonal Bank", "ZugerKB", "ZGKB", "ZKB Zug", "ZKB", "Zuger Kantonalbank AG"],
            "location": "zug",
            "institution_type": "cantonal_bank",
            "clearing_code": "0787",
            "headquarters": "Bahnhofstrasse 1, Postfach, 6301 Zug"
        }
    },
    "organization_postfinance_sa": {
        "name": "PostFinance SA",
        "aliases": [
            "PostFinance", "PostFinance SA", "PostFinance AG", "Swiss Post PostFinance"
        ],
        "patterns": [
            r"(?i)\b(?:PostFinance(?:\s+SA|\s+AG)?|Post\s*Finance)\b",
            r"(?i)\bpostfinance\.ch\b",
            r"(?i)\bPOFICHBEXXX\b"
        ],
        "location_id": "location_bern",
        "properties": {
            "aliases": ["PostFinance", "PostFinance SA", "PostFinance AG", "Swiss Post PostFinance"],
            "location": "bern",
            "institution_type": "financial_institution",
            "headquarters": "Mingerstrasse 20, 3030 Bern"
        }
    },
    "organization_zuercher_kantonalbank": {
        "name": "Zürcher Kantonalbank",
        "aliases": [
            "Zürcher Kantonalbank", "Zuercher Kantonalbank", "ZKB Zürich"
        ],
        "patterns": [
            r"(?i)\b(?:Zürcher\s+Kantonalbank|Zuercher\s+Kantonalbank)\b",
            r"(?i)\bzkb\.ch\b"
        ],
        "location_id": "location_zurich",
        "properties": {
            "aliases": ["Zürcher Kantonalbank", "Zuercher Kantonalbank", "ZKB Zürich"],
            "location": "zurich",
            "institution_type": "cantonal_bank",
            "clearing_code": "0700",
            "headquarters": "Bahnhofstrasse 9, 8001 Zürich"
        }
    },
    "organization_ubs_switzerland_ag": {
        "name": "UBS Switzerland AG",
        "aliases": ["UBS", "UBS AG", "UBS Switzerland AG", "Union Bank of Switzerland"],
        "patterns": [
            r"(?i)\b(?:UBS(?:\s+Switzerland(?:\s+AG)?)?|UBS\s+AG)\b",
            r"(?i)\bubs\.com\b"
        ],
        "location_id": "location_zurich",
        "properties": {
            "aliases": ["UBS", "UBS AG", "UBS Switzerland AG", "Union Bank of Switzerland"],
            "location": "zurich",
            "institution_type": "bank",
            "headquarters": "Bahnhofstrasse 45, 8001 Zürich"
        }
    },
    "organization_credit_suisse_ag": {
        "name": "Credit Suisse AG",
        "aliases": ["Credit Suisse", "Credit Suisse AG", "Credit Suisse (Schweiz) AG"],
        "patterns": [
            r"(?i)\b(?:Credit\s+Suisse(?:\s+AG|\s+\(Schweiz\)\s+AG)?)\b",
            r"(?i)\bcredit-suisse\.com\b"
        ],
        "location_id": "location_zurich",
        "properties": {
            "aliases": ["Credit Suisse", "Credit Suisse AG", "Credit Suisse (Schweiz) AG"],
            "location": "zurich",
            "institution_type": "bank",
            "headquarters": "Paradeplatz 8, 8001 Zürich"
        }
    },
    "organization_raiffeisen_schweiz": {
        "name": "Raiffeisen Schweiz",
        "aliases": ["Raiffeisen", "Raiffeisenbank", "Raiffeisen Schweiz"],
        "patterns": [
            r"(?i)\b(?:Raiffeisenbank|Raiffeisen\s+Schweiz)\b",
            r"(?i)\braiffeisen\.ch\b"
        ],
        "location_id": "location_st_gallen",
        "properties": {
            "aliases": ["Raiffeisen", "Raiffeisenbank", "Raiffeisen Schweiz"],
            "location": "st_gallen",
            "institution_type": "cooperative_bank",
            "headquarters": "Raiffeisenplatz 4, 9001 St. Gallen"
        }
    }
}


class KnowledgeGraphExtractor:
    """Extracts structured entities, relationships, and document links from document text."""

    def __init__(self,
                 provider: Optional[str] = None,
                 theme_resolver: Optional[ThemeResolver] = None):
        self.provider = provider or settings.LLM_PROVIDER
        self.theme_resolver = theme_resolver or ThemeResolver()

    def attach_theme(self, doc_graph: DocumentKnowledgeGraph, doc_type: str) -> DocumentKnowledgeGraph:
        """Add the document's taxonomy theme hub (node + CATEGORIZED_AS link/edge). Idempotent."""
        resolved = self.theme_resolver.resolve(doc_type)
        if not resolved:
            return doc_graph

        root_id, root_name = resolved
        theme_id = canonicalize_node_id(THEME_NODE_TYPE, root_id)
        existing_ids = {n.node_id for n in doc_graph.nodes}

        if theme_id not in existing_ids:
            doc_graph.nodes.append(EntityNode(
                node_id=theme_id,
                node_type=THEME_NODE_TYPE,
                name=root_name,
                properties={
                    "taxonomy_root": root_id,
                    "is_fallback": root_id == UNCLASSIFIED_THEME_ID,
                },
            ))

        # Document -> theme (documents are not knowledge_nodes, so this lives in document_entity_links)
        if not any(l.node_id == theme_id and l.role == THEME_RELATION for l in doc_graph.links):
            doc_graph.links.append(DocumentEntityLink(
                sha256_hash=doc_graph.sha256_hash,
                node_id=theme_id,
                role=THEME_RELATION,
                confidence=1.0,
            ))

        # Category node -> theme, only for the node derived from this doc_type and only if it is
        # present in this graph (knowledge_edges enforces FKs on both endpoints).
        category_ids = {
            canonicalize_node_id("contract_type", doc_type),
            canonicalize_node_id("document_category", doc_type),
        }
        existing_edges = {(e.source_id, e.target_id, e.relation_type) for e in doc_graph.edges}
        for cat_id in category_ids & existing_ids:
            if (cat_id, theme_id, THEME_RELATION) not in existing_edges:
                doc_graph.edges.append(EntityEdge(
                    source_id=cat_id,
                    target_id=theme_id,
                    relation_type=THEME_RELATION,
                    weight=1.0,
                    properties={"context": f"Taxonomy domain of {doc_type}"},
                ))

        return doc_graph

    def _extract_heuristic_fallback(self,
                                    text: str,
                                    sha256_hash: str,
                                    filename: str = "",
                                    doc_type: str = "") -> DocumentKnowledgeGraph:
        """Fast, deterministic heuristic and regex-based entity and relationship extractor."""
        nodes: Dict[str, EntityNode] = {}
        edges: List[EntityEdge] = []
        links: List[DocumentEntityLink] = []

        # Known contract types to separate from general document categories
        KNOWN_CONTRACT_TYPES = {
            "nda", "employment_contract", "service_agreement", "lease_agreement",
            "lease_contract", "consulting_agreement", "license_agreement",
            "procurement_contract", "arbeitsvertrag", "mietvertrag",
            "dienstleistungsvertrag", "legal_contract"
        }

        # Blacklist of false-positive organization / entity matches
        ORG_BLACKLIST = {
            "memory bank", "data bank", "piggy bank", "blood bank", "power bank",
            "court order", "supreme court decision", "press corp", "marine corp",
            "system architecture", "technical architecture", "table of contents",
            "confidential", "all rights reserved", "general terms", "annex",
            "unterzeichnet", "signataire", "signé", "unterschrift", "zwischen",
            "order document regarding", "court order document regarding",
            "verschiebung", "verschiebungsdatum", "kontoauszug", "rechnung",
            "buchungsanzeige", "mitteilung", "belastung", "gutschrift",
            "unstimmigkeiten", "unstimmigkeiten sind der bank", "name der bank",
            "ihre bank", "zustellung", "abrechnung", "zusatzblatt", "schuldzinsen",
            "hypothek auskonto", "auszahlungsbetrag", "bankauszug", "saldo", "bvr"
        }

        # Blacklist of false-positive person / signatory matches
        PERSON_BLACKLIST = {
            "table of contents", "executive summary", "general terms", "project manager",
            "software engineer", "managing director", "technical overview", "dear sir",
            "yours sincerely", "first party", "second party", "unterschrift", "signature",
            "signé par", "signed by", "arbeitgeber", "arbeitnehmer", "vermieter", "mieter"
        }

        # 1. Extract Document Type / Category Node
        if doc_type:
            norm_dt = doc_type.strip().lower().replace(" ", "_")
            if any(k in norm_dt for k in KNOWN_CONTRACT_TYPES):
                node_type = "contract_type"
                role = "contractual_framework"
            else:
                node_type = "document_category"
                role = "category_classification"

            dt_id = canonicalize_node_id(node_type, doc_type)
            nodes[dt_id] = EntityNode(
                node_id=dt_id,
                node_type=node_type,
                name=doc_type.replace("_", " ").title()
            )
            links.append(DocumentEntityLink(sha256_hash=sha256_hash, node_id=dt_id, role=role))

        # 2. Canonical Banking & Institutional Entity Resolution (Deterministic Priority)
        full_corpus = f"{filename} {text}"
        matched_canonical_orgs = set()

        for org_id, org_meta in KNOWN_BANKING_ORGANIZATIONS.items():
            for pat in org_meta["patterns"]:
                if re.search(pat, full_corpus):
                    matched_canonical_orgs.add(org_id)
                    break

        # Disambiguate standalone 'ZKB'
        if re.search(r'\bZKB\b', full_corpus) and "organization_zuger_kantonalbank" not in matched_canonical_orgs and "organization_zuercher_kantonalbank" not in matched_canonical_orgs:
            has_zug = bool(re.search(r'(?i)\b(?:Zug|Steinhausen|Baar|Cham|Rotkreuz|6300|6301|6312|zugerkb)\b', full_corpus))
            has_zurich = bool(re.search(r'(?i)\b(?:Zürich|Zurich|8001|8000|zkb\.ch)\b', full_corpus))
            if has_zug or not has_zurich:
                matched_canonical_orgs.add("organization_zuger_kantonalbank")
            else:
                matched_canonical_orgs.add("organization_zuercher_kantonalbank")

        # Materialize canonical organization nodes and headquarters edges
        for org_id in matched_canonical_orgs:
            org_meta = KNOWN_BANKING_ORGANIZATIONS[org_id]
            nodes[org_id] = EntityNode(
                node_id=org_id,
                node_type="organization",
                name=org_meta["name"],
                properties=org_meta.get("properties", {})
            )
            links.append(DocumentEntityLink(sha256_hash=sha256_hash, node_id=org_id, role="counterparty", confidence=1.0))

            # Automatically establish headquarters location and relationship edge
            loc_id = org_meta.get("location_id")
            if loc_id:
                loc_clean_name = loc_id.replace("location_", "").replace("_", " ").title()
                if loc_id not in nodes:
                    nodes[loc_id] = EntityNode(node_id=loc_id, node_type="location", name=loc_clean_name)
                edges.append(EntityEdge(
                    source_id=org_id,
                    target_id=loc_id,
                    relation_type="LOCATED_IN",
                    weight=1.0,
                    properties={"context": f"Headquarters of {org_meta['name']}"}
                ))

        # 3. Extract Signatories / Parties (with newline protection and alias mapping)
        sign_patterns = [
            r"(?i:\b(?:Signed by|Signé par|Unterschrift|Signatory|Signature|Signatures)\b)[\s:]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})",
            r"(?i:\b(?:Between|Entre|Zwischen)\b)[\s:]+([A-Z][a-zA-Z0-9\.\s\(\)-]+?)(?:\s*(?i:and|et|und|&)|\n)",
            r"(?i:\b(?:Employer|Arbeitgeber|Employeur)\b)[\s:]+([A-Z][a-zA-Z0-9\.\s\(\)-]+?)(?:\n|,|\.)",
            r"(?i:\b(?:Employee|Arbeitnehmer|Employé)\b)[\s:]+([A-Z][a-zA-Z0-9\.\s\(\)-]+?)(?:\n|,|\.)",
            r"(?i:\b(?:Tenant|Landlord|Vermieter|Mieter|Locataire|Bailleur)\b)[\s:]+([A-Z][a-zA-Z0-9\.\s\(\)-]+?)(?:\n|,|\.)",
        ]

        def is_clean_party(val: str) -> bool:
            if not val or len(val) < 3 or len(val) > 55:
                return False
            # Reject multiline fragments / OCR noise
            if "\n" in val or "\r" in val or "\t" in val:
                return False
            # Reject strings ending with punctuation or starting with non-alphanumeric
            if re.search(r'^[^\w]|[.,;:!?]$', val):
                return False
            low = val.lower().strip()
            # Reject blacklisted terms
            if any(b in low for b in ORG_BLACKLIST | PERSON_BLACKLIST):
                return False
            # Reject if it's purely a location name
            if low in {"zug", "zurich", "zürich", "ottenbach", "steinhausen", "baar", "cham", "geneva", "genève", "bern", "basel", "switzerland", "schweiz", "kanton zug", "kanton zürich"}:
                return False
            return True

        parties_found = set()
        for pat in sign_patterns:
            for match in re.finditer(pat, text):
                val = match.group(1).strip()
                val = re.sub(r'\s*\([^)]*\)', '', val).strip()
                if is_clean_party(val) and not any(w in val.lower() for w in ["agreement", "contract", "page", "date"]):
                    parties_found.add(val)

        # Extract explicit Organization pattern (horizontal whitespace only, preventing multiline grab)
        org_explicit = re.findall(
            r'\b([A-Z][A-Za-z0-9 \.\-&]{1,40}\b(?:AG|SA|GmbH|Sàrl|LLC|Ltd|Inc|Bank|Kantonalbank|Kantonal\s+Bank|Banque|Banca|Corp|Court|Kantonsgericht|Bezirksgericht|Steueramt))\b',
            text
        )
        for org in org_explicit:
            clean_org = org.strip()
            if is_clean_party(clean_org) and not any(w in clean_org.lower() for w in ["agreement", "contract"]):
                parties_found.add(clean_org)

        # 4. Known Company/Institution indicators & Canonical Aliasing
        org_indicators = [
            "AG", "SA", "GmbH", "Sàrl", "LLC", "Ltd", "Inc", "Bank", "Kantonalbank",
            "Banque", "Banca", "PostFinance", "Finanz", "Pensionskasse", "Versicherung",
            "Kantonsgericht", "Bezirksgericht", "Steueramt", "Swiss", "Corp", "Court"
        ]
        for p in parties_found:
            # Check if this party maps to an already recognized or known canonical organization
            mapped_canonical = None
            p_low = p.lower()
            for org_id, org_meta in KNOWN_BANKING_ORGANIZATIONS.items():
                if any(alias.lower() in p_low or p_low in alias.lower() for alias in org_meta["aliases"]):
                    mapped_canonical = org_id
                    break

            if mapped_canonical:
                if mapped_canonical not in nodes:
                    org_meta = KNOWN_BANKING_ORGANIZATIONS[mapped_canonical]
                    nodes[mapped_canonical] = EntityNode(
                        node_id=mapped_canonical,
                        node_type="organization",
                        name=org_meta["name"],
                        properties=org_meta.get("properties", {})
                    )
                if not any(lnk.node_id == mapped_canonical for lnk in links):
                    links.append(DocumentEntityLink(sha256_hash=sha256_hash, node_id=mapped_canonical, role="counterparty", confidence=1.0))
                continue

            is_org = any(ind in p for ind in org_indicators)
            n_type = "organization" if is_org else "person"
            node_id = canonicalize_node_id(n_type, p)

            if node_id not in nodes:
                nodes[node_id] = EntityNode(node_id=node_id, node_type=n_type, name=p)

            role = "counterparty" if is_org else "signatory"
            links.append(DocumentEntityLink(sha256_hash=sha256_hash, node_id=node_id, role=role))


        # 4. Extract Legal Statutes (e.g. OR 253, Art. 320 OR, ZGB, StGB)
        statute_matches = re.findall(r'\b(?:Art\.?\s*\d+\w*|\b[A-Z]{2,4}\b\s+Art\.?\s*\d+)', text, re.IGNORECASE)
        for stat in set(statute_matches[:5]):
            st_id = canonicalize_node_id("statute", stat)
            if st_id not in nodes:
                nodes[st_id] = EntityNode(node_id=st_id, node_type="statute", name=stat.upper())
            links.append(DocumentEntityLink(sha256_hash=sha256_hash, node_id=st_id, role="governing_law"))

        # 5. Extract Locations (Comprehensive Swiss cantons/communes + international hubs)
        location_patterns = {
            "location_ottenbach": {"name": "Ottenbach", "regex": r'\b(?:Ottenbach|8913\s*Ottenbach)\b'},
            "location_steinhausen": {"name": "Steinhausen", "regex": r'\b(?:Steinhausen|6312\s*Steinhausen)\b'},
            "location_zug": {"name": "Zug", "regex": r'\b(?:Zug|Kanton\s+Zug|Canton\s+de\s+Zoug|Zoug|6300\s*Zug)\b'},
            "location_baar": {"name": "Baar", "regex": r'\b(?:Baar|6340\s*Baar)\b'},
            "location_cham": {"name": "Cham", "regex": r'\b(?:Cham|6330\s*Cham)\b'},
            "location_rotkreuz": {"name": "Rotkreuz", "regex": r'\b(?:Rotkreuz|Risch[- ]Rotkreuz|6343\s*Rotkreuz)\b'},
            "location_affoltern": {"name": "Affoltern am Albis", "regex": r'\b(?:Affoltern\s+am\s+Albis|Affoltern|8910\s*Affoltern)\b'},
            "location_switzerland": {"name": "Switzerland", "regex": r'\b(?:Switzerland|Schweiz|Suisse|Svizzera|Helvetia|CH-\d{4})\b'},
            "location_zurich": {"name": "Zurich", "regex": r'\b(?:Zurich|Zürich|Kanton\s+Zürich|8001\s*Zürich|8000\s*Zürich)\b'},
            "location_geneva": {"name": "Geneva", "regex": r'\b(?:Geneva|Genève|Genf|Canton\s+de\s+Genève)\b'},
            "location_lausanne": {"name": "Lausanne", "regex": r'\b(?:Lausanne|1000\s*Lausanne)\b'},
            "location_basel": {"name": "Basel", "regex": r'\b(?:Basel|Bâle|Basel-Stadt|Basel-Landschaft)\b'},
            "location_bern": {"name": "Bern", "regex": r'\b(?:Bern|Berne|Canton\s+de\s+Berne)\b'},
            "location_luzern": {"name": "Luzern", "regex": r'\b(?:Luzern|Lucerne)\b'},
            "location_st_gallen": {"name": "St. Gallen", "regex": r'\b(?:St\.?\s*Gallen|Sankt\s+Gallen)\b'},
            "location_lugano": {"name": "Lugano", "regex": r'\b(?:Lugano)\b'},
            "location_winterthur": {"name": "Winterthur", "regex": r'\b(?:Winterthur)\b'},
            "location_neuchatel": {"name": "Neuchâtel", "regex": r'\b(?:Neuchâtel|Neuchatel)\b'},
            "location_fribourg": {"name": "Fribourg", "regex": r'\b(?:Fribourg|Freiburg)\b'},
            "location_sion": {"name": "Sion", "regex": r'\b(?:Sion|Sitten)\b'},
            "location_chur": {"name": "Chur", "regex": r'\b(?:Chur|Coire)\b'},
            "location_biel": {"name": "Biel/Bienne", "regex": r'\b(?:Biel|Bienne)\b'},
            "location_aarau": {"name": "Aarau", "regex": r'\b(?:Aarau|Aargau)\b'},
            "location_solothurn": {"name": "Solothurn", "regex": r'\b(?:Solothurn|Soleure)\b'},
            "location_schaffhausen": {"name": "Schaffhausen", "regex": r'\b(?:Schaffhausen|Schaffhouse)\b'},
            "location_bellinzona": {"name": "Bellinzona", "regex": r'\b(?:Bellinzona)\b'},
            "location_vaud": {"name": "Vaud", "regex": r'\b(?:Canton\s+de\s+Vaud|Vaud)\b'},
            "location_valais": {"name": "Valais", "regex": r'\b(?:Valais|Wallis)\b'},
            "location_ticino": {"name": "Ticino", "regex": r'\b(?:Ticino|Tessin)\b'},
            "location_paris": {"name": "Paris", "regex": r'\b(?:Paris)\b'},
            "location_london": {"name": "London", "regex": r'\b(?:London)\b'},
            "location_new_york": {"name": "New York", "regex": r'\b(?:New\s+York|NYC)\b'},
            "location_berlin": {"name": "Berlin", "regex": r'\b(?:Berlin)\b'},
            "location_frankfurt": {"name": "Frankfurt", "regex": r'\b(?:Frankfurt)\b'},
            "location_munich": {"name": "Munich", "regex": r'\b(?:Munich|München)\b'},
            "location_brussels": {"name": "Brussels", "regex": r'\b(?:Brussels|Bruxelles)\b'},
            "location_amsterdam": {"name": "Amsterdam", "regex": r'\b(?:Amsterdam)\b'},
            "location_milan": {"name": "Milan", "regex": r'\b(?:Milan|Milano)\b'},
            "location_rome": {"name": "Rome", "regex": r'\b(?:Rome|Roma)\b'},
            "location_madrid": {"name": "Madrid", "regex": r'\b(?:Madrid)\b'},
            "location_vienna": {"name": "Vienna", "regex": r'\b(?:Vienna|Wien)\b'},
            "location_tenerife": {"name": "Tenerife", "regex": r'\b(?:Tenerife)\b'},
            "location_luxembourg": {"name": "Luxembourg", "regex": r'\b(?:Luxembourg|Luxemburg)\b'},
            "location_liechtenstein": {"name": "Liechtenstein", "regex": r'\b(?:Liechtenstein|Vaduz)\b'},
        }

        search_corpus = f"{filename} {text}"
        for loc_id, loc_info in location_patterns.items():
            if re.search(loc_info["regex"], search_corpus, re.IGNORECASE):
                if loc_id not in nodes:
                    nodes[loc_id] = EntityNode(node_id=loc_id, node_type="location", name=loc_info["name"])
                links.append(DocumentEntityLink(sha256_hash=sha256_hash, node_id=loc_id, role="mention"))

        # 6. Universal Currency Units & Standard Financial Pillars (Federator Hubs)
        CURRENCY_MAP = {
            r"\b(?:CHF|sFr\.?|Franken)\b": "CHF",
            r"\b(?:EUR|€|Euro)\b": "EUR",
            r"\b(?:USD|\$|US-Dollar)\b": "USD",
            r"\b(?:GBP|£|Pound)\b": "GBP",
            r"\b(?:JPY|¥|Yen)\b": "JPY"
        }

        found_currencies = set()
        for pat, code in CURRENCY_MAP.items():
            if re.search(pat, text, re.IGNORECASE):
                cur_id = canonicalize_node_id("currency", code)
                if cur_id not in nodes:
                    nodes[cur_id] = EntityNode(node_id=cur_id, node_type="currency", name=code)
                links.append(DocumentEntityLink(sha256_hash=sha256_hash, node_id=cur_id, role="currency_unit"))
                found_currencies.add(cur_id)

        PILLAR_PATTERNS = {
            "rent": r"\b(?:Miete|Mietzins|Loyer|Rent|Lease payment|Bail)\b",
            "salary": r"\b(?:Lohn|Gehalt|Salär|Salaire|Salary|Remuneration|Bonus|Vergütung)\b",
            "mortgage": r"\b(?:Hypothek|Hypothekardarlehen|Mortgage|Prêt hypothécaire)\b",
            "fee": r"\b(?:Gebühr|Honorar|Frais|Courtage|Commission|Fee|Management fee)\b",
            "fine": r"\b(?:Busse|Konventionalstrafe|Pénalité|Fine|Penalty|Schadensersatz)\b",
            "interest": r"\b(?:Zins|Verzugszins|Intérêt|Interest rate|Yield)\b",
            "insurance_premium": r"\b(?:Prämie|Prime d'assurance|AHV|ALV|Pensionskasse|Insurance premium)\b",
        }

        found_pillars = set()
        for pillar, pattern in PILLAR_PATTERNS.items():
            if re.search(pattern, text, re.IGNORECASE):
                p_id = canonicalize_node_id("financial_pillar", pillar)
                if p_id not in nodes:
                    nodes[p_id] = EntityNode(
                        node_id=p_id, 
                        node_type="financial_pillar", 
                        name=pillar.replace("_", " ").title()
                    )
                links.append(DocumentEntityLink(sha256_hash=sha256_hash, node_id=p_id, role="financial_term"))
                found_pillars.add(p_id)

        # 7. Extract Project / Operational Identifiers
        project_matches = re.findall(r'\b(?:Project|Projekt|Ref|Reference|Contract-No|Dossier)[\s:#]+([A-Z0-9]{2,8}(?:[-_][A-Z0-9]+){1,3})\b', text, re.IGNORECASE)
        for prj in set(project_matches[:3]):
            prj_label = prj.strip().upper()
            prj_id = canonicalize_node_id("project_code", prj_label)
            if prj_id not in nodes:
                nodes[prj_id] = EntityNode(node_id=prj_id, node_type="project_code", name=prj_label)
            links.append(DocumentEntityLink(sha256_hash=sha256_hash, node_id=prj_id, role="project_reference"))

        # 8. Extract Milestone / Lifecycle Dates
        milestone_matches = re.findall(r'\b(?:Effective Date|Completion Date|Inkrafttreten|Fälligkeit|Deadline|Termin|Milestone)[\s:]+(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2})\b', text, re.IGNORECASE)
        for ms_date in set(milestone_matches[:3]):
            ms_id = canonicalize_node_id("milestone_date", ms_date)
            if ms_id not in nodes:
                nodes[ms_id] = EntityNode(node_id=ms_id, node_type="milestone_date", name=f"Milestone {ms_date}")
            links.append(DocumentEntityLink(sha256_hash=sha256_hash, node_id=ms_id, role="milestone"))

        # 9. Dense Bipartite & Cross-Archetype Graph Edges
        party_node_ids = [n.node_id for n in nodes.values() if n.node_type in ["person", "organization"]]
        loc_node_ids = [n.node_id for n in nodes.values() if n.node_type == "location"]
        stat_node_ids = [n.node_id for n in nodes.values() if n.node_type == "statute"]
        val_node_ids = [n.node_id for n in nodes.values() if n.node_type == "monetary_value"]
        prj_node_ids = [n.node_id for n in nodes.values() if n.node_type == "project_code"]
        dt_id = canonicalize_node_id("contract_type", doc_type) if doc_type else None

        # 9a. Parties co-occurring in document (PARTY_TO)
        for i in range(len(party_node_ids)):
            for j in range(i + 1, len(party_node_ids)):
                edges.append(EntityEdge(
                    source_id=party_node_ids[i],
                    target_id=party_node_ids[j],
                    relation_type="PARTY_TO",
                    weight=1.0,
                    properties={"context": f"Co-parties in {filename or sha256_hash[:8]}"}
                ))

        # 9b. Contract Type <-> Parties (PARTY_TO)
        if dt_id and dt_id in nodes:
            for pid in party_node_ids:
                edges.append(EntityEdge(
                    source_id=pid,
                    target_id=dt_id,
                    relation_type="PARTY_TO",
                    weight=1.0,
                    properties={"context": f"Party involved in {doc_type}"}
                ))

        # 9c. Parties -> Location (LOCATED_IN for organizations, RESIDES_IN for persons)
        for pid in party_node_ids:
            p_node = nodes.get(pid)
            rel_type = "LOCATED_IN" if (p_node and p_node.node_type == "organization") else "RESIDES_IN"
            for lid in loc_node_ids:
                edges.append(EntityEdge(
                    source_id=pid,
                    target_id=lid,
                    relation_type=rel_type,
                    weight=1.0,
                    properties={"context": f"Jurisdiction/Residence in {filename or sha256_hash[:8]}"}
                ))

        # 9d. Contract Type -> Location (JURISDICTION)
        if dt_id and dt_id in nodes:
            for lid in loc_node_ids:
                edges.append(EntityEdge(
                    source_id=dt_id,
                    target_id=lid,
                    relation_type="JURISDICTION",
                    weight=1.0,
                    properties={"context": f"Jurisdiction for {doc_type}"}
                ))

        # 9e. Parties & Contract Type -> Statutes (SUBJECT_TO / GOVERNED_BY)
        for stat_id in stat_node_ids:
            for pid in party_node_ids:
                edges.append(EntityEdge(
                    source_id=pid,
                    target_id=stat_id,
                    relation_type="SUBJECT_TO",
                    weight=1.0,
                    properties={"context": "Statutory governance"}
                ))
            if dt_id and dt_id in nodes:
                edges.append(EntityEdge(
                    source_id=dt_id,
                    target_id=stat_id,
                    relation_type="GOVERNED_BY",
                    weight=1.0,
                    properties={"context": "Governing statutory framework"}
                ))

        # 9f. Financial Pillars -> Currencies (DENOMINATED_IN)
        for p_id in found_pillars:
            for c_id in found_currencies:
                edges.append(EntityEdge(
                    source_id=p_id,
                    target_id=c_id,
                    relation_type="DENOMINATED_IN",
                    weight=1.0,
                    properties={"context": f"Document {filename or sha256_hash[:8]}"}
                ))

        # 9g. Contract Type -> Financial Pillars & Currencies (INVOLVES_PAYMENT / STIPULATES_CURRENCY)
        if dt_id and dt_id in nodes:
            for p_id in found_pillars:
                edges.append(EntityEdge(
                    source_id=dt_id,
                    target_id=p_id,
                    relation_type="INVOLVES_PAYMENT",
                    weight=1.0,
                    properties={"context": f"Document {filename or sha256_hash[:8]}"}
                ))
            for c_id in found_currencies:
                edges.append(EntityEdge(
                    source_id=dt_id,
                    target_id=c_id,
                    relation_type="STIPULATES_CURRENCY",
                    weight=1.0,
                    properties={"context": f"Document {filename or sha256_hash[:8]}"}
                ))

        # 9h. Parties -> Financial Pillars (PAYS)
        for pid in party_node_ids:
            for p_id in found_pillars:
                edges.append(EntityEdge(
                    source_id=pid,
                    target_id=p_id,
                    relation_type="PAYS",
                    weight=1.0,
                    properties={"context": f"Financial flow in {filename or sha256_hash[:8]}"}
                ))

        # 9i. Financial Pillars -> Statutes (GOVERNED_BY)
        for p_id in found_pillars:
            for stat_id in stat_node_ids:
                edges.append(EntityEdge(
                    source_id=p_id,
                    target_id=stat_id,
                    relation_type="GOVERNED_BY",
                    weight=1.0,
                    properties={"context": "Statutory financial governance"}
                ))

        # 9g. Parties & Contract Type -> Project Codes (ASSIGNED_TO)
        for prj_id in prj_node_ids:
            for pid in party_node_ids:
                edges.append(EntityEdge(
                    source_id=pid,
                    target_id=prj_id,
                    relation_type="ASSIGNED_TO",
                    weight=1.0,
                    properties={"context": "Project assignment"}
                ))
            if dt_id and dt_id in nodes:
                edges.append(EntityEdge(
                    source_id=dt_id,
                    target_id=prj_id,
                    relation_type="ASSIGNED_TO",
                    weight=1.0,
                    properties={"context": "Project reference"}
                ))

        # Deduplicate edges by (source_id, target_id, relation_type)
        unique_edges = []
        seen_edges = set()
        for edge in edges:
            edge_key = (edge.source_id, edge.target_id, edge.relation_type)
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                unique_edges.append(edge)

        return DocumentKnowledgeGraph(
            sha256_hash=sha256_hash,
            nodes=list(nodes.values()),
            edges=unique_edges,
            links=links
        )

    def extract_knowledge_graph(self,
                                text: str,
                                sha256_hash: str,
                                filename: str = "",
                                doc_type: str = "",
                                doc_date: str = "") -> DocumentKnowledgeGraph:
        """Extract entities/relationships, then attach the document's taxonomy theme hub."""
        doc_graph = self._extract_entity_graph(
            text=text,
            sha256_hash=sha256_hash,
            filename=filename,
            doc_type=doc_type,
            doc_date=doc_date,
        )
        try:
            return self.attach_theme(doc_graph, doc_type)
        except Exception as e:
            # Theme hubs are additive; never let them break entity extraction.
            logger.warning(f"Theme attachment failed for {sha256_hash[:12]}: {e}")
            return doc_graph

    def _extract_entity_graph(self,
                              text: str,
                              sha256_hash: str,
                              filename: str = "",
                              doc_type: str = "",
                              doc_date: str = "") -> DocumentKnowledgeGraph:
        """Extract structured Knowledge Graph entities and relationships from document text."""
        if not text or not text.strip():
            return self._extract_heuristic_fallback(text="", sha256_hash=sha256_hash, filename=filename, doc_type=doc_type)

        # High-throughput ingestion: default to deterministic Swiss legal regex/taxonomy (< 1ms)
        mode = getattr(settings, "GRAPH_EXTRACTOR_MODE", "heuristic")
        if mode == "heuristic":
            return self._extract_heuristic_fallback(text=text, sha256_hash=sha256_hash, filename=filename, doc_type=doc_type)

        # Attempt structured LLM extraction (optional / low-volume)
        if self.provider in ["auto", "ollama", "openrouter"]:
            try:
                prompt = f"""You are a domain-expert Knowledge Graph ontology engineer and data certifier for a legal, corporate, and document repository.

Extract structured entities and semantic relationships from the provided document text according to our strict entity taxonomy.

### ENTITY ONTOLOGY RULES:
1. "currency": Canonical monetary unit (ISO code or symbol).
   - ONLY allowed values: "CHF", "EUR", "USD", "GBP", "JPY".
   - Do NOT create nodes for raw numeric amounts (e.g., do NOT extract "1,200 CHF" or "$50,000").
2. "financial_pillar": High-level contractual financial classifications.
   - Standard categories:
     * "rent": Lease payments, rental income, tenant rent, storage rent.
     * "salary": Wages, base compensation, executive pay, director fees, bonuses.
     * "mortgage": Hypothek, property loans, secured debt instruments.
     * "fee": Advisory fees, retainer, transaction fees, management fees, notary charges.
     * "fine": Penalties, contractual damages, late charges, administrative sanctions.
     * "interest": Loan interest, compounding yield, coupon payments, late interest (Verzugszins).
     * "insurance_premium": Policy payments, social security contributions (AHV/ALV).
3. "organization": Bona fide corporate, institutional, or government bodies (e.g., "Swisscom AG", "Kantonales Steueramt Zürich"). Reject UI terms or technical phrases.
4. "person": Real human beings (First Last). Reject roles ("Landlord"), titles, or section labels.
5. "contract_type": Legal instrument classification (e.g., "Mietvertrag", "Employment Contract", "Loan Agreement").
6. "location": Standard cities or cantons (e.g., "Zurich", "Geneva", "Zug").
7. "statute": Legal code or article (e.g., "Art. 253 OR", "ZGB", "Art. 320 OR").

### RELATIONSHIP SCHEMA:
- (organization|person) -[:PAYS|RECEIVES]-> (financial_pillar)
- (financial_pillar) -[:DENOMINATED_IN]-> (currency)
- (contract_type) -[:INVOLVES_PAYMENT]-> (financial_pillar)
- (contract_type) -[:STIPULATES_CURRENCY]-> (currency)
- (financial_pillar) -[:GOVERNED_BY]-> (statute)

Document Metadata:
- Filename: {filename}
- Category: {doc_type}
- Date: {doc_date}

Document Text:
\"\"\"
{text[:2500]}
\"\"\"

Output strictly valid JSON conforming to this structure:
{{
  "entities": [
    {{"type": "currency", "name": "CHF"}},
    {{"type": "financial_pillar", "name": "rent"}},
    {{"type": "person", "name": "Jane Doe"}},
    {{"type": "organization", "name": "Immobilien AG"}}
  ],
  "relationships": [
    {{"source": "Jane Doe", "target": "rent", "relation": "PAYS"}},
    {{"source": "Immobilien AG", "target": "rent", "relation": "RECEIVES"}},
    {{"source": "rent", "target": "CHF", "relation": "DENOMINATED_IN"}}
  ]
}}
Do NOT include markdown explanations, markdown fences, or text outside the JSON object.
"""
                resp_text = None
                if self.provider in ["auto", "ollama"]:
                    import time
                    t0 = time.time()
                    target_model = settings.chat_model
                    try:
                        resp = httpx.post(
                            f"{settings.chat_url}/api/chat",
                            json={
                                "model": target_model,
                                "messages": [{"role": "user", "content": prompt}],
                                "stream": False,
                                "keep_alive": settings.OLLAMA_KEEP_ALIVE,
                                "options": {
                                    "temperature": 0.1,
                                    "num_ctx": getattr(settings, "OLLAMA_NUM_CTX", 2048)
                                }
                            },
                            timeout=settings.OLLAMA_TIMEOUT
                        )
                        elapsed_ms = (time.time() - t0) * 1000
                        from backend.ai.telemetry import workload_telemetry
                        if resp.status_code == 200:
                            workload_telemetry.record_chat(
                                latency_ms=elapsed_ms,
                                success=True,
                                node=workload_telemetry.chat_active_node,
                                model=target_model
                            )
                            resp_text = resp.json().get("message", {}).get("content", "")
                        else:
                            workload_telemetry.record_chat(
                                latency_ms=elapsed_ms,
                                success=False,
                                node=workload_telemetry.chat_active_node,
                                model=target_model
                            )
                    except Exception:
                        elapsed_ms = (time.time() - t0) * 1000
                        from backend.ai.telemetry import workload_telemetry
                        workload_telemetry.record_chat(
                            latency_ms=elapsed_ms,
                            success=False,
                            node=workload_telemetry.chat_active_node,
                            model=target_model
                        )
                        raise

                if resp_text:
                    # Clean JSON markdown fences
                    clean = re.sub(r'^```json\s*', '', resp_text.strip(), flags=re.IGNORECASE)
                    clean = re.sub(r'\s*```$', '', clean)
                    data = json.loads(clean)

                    nodes: Dict[str, EntityNode] = {}
                    links: List[DocumentEntityLink] = []
                    edges: List[EntityEdge] = []

                    for ent in data.get("entities", []):
                        e_type = ent.get("type", "person").lower()
                        e_name = ent.get("name", "").strip()
                        if e_name:
                            node_id = canonicalize_node_id(e_type, e_name)
                            if node_id not in nodes:
                                nodes[node_id] = EntityNode(node_id=node_id, node_type=e_type, name=e_name)
                            role = "currency_unit" if e_type == "currency" else ("financial_term" if e_type == "financial_pillar" else "mention")
                            links.append(DocumentEntityLink(sha256_hash=sha256_hash, node_id=node_id, role=role))

                    name_to_id = {n.name.lower(): n.node_id for n in nodes.values()}
                    for rel in data.get("relationships", []):
                        s_name = rel.get("source", "").strip()
                        t_name = rel.get("target", "").strip()
                        r_type = rel.get("relation", "PARTY_TO").upper()
                        if s_name and t_name:
                            s_id = name_to_id.get(s_name.lower()) or canonicalize_node_id("entity", s_name)
                            t_id = name_to_id.get(t_name.lower()) or canonicalize_node_id("entity", t_name)
                            edges.append(EntityEdge(source_id=s_id, target_id=t_id, relation_type=r_type))

                    if nodes:
                        return DocumentKnowledgeGraph(
                            sha256_hash=sha256_hash,
                            nodes=list(nodes.values()),
                            edges=edges,
                            links=links
                        )
            except Exception as e:
                logger.debug(f"LLM KG extraction fallback triggered: {e}")

        # Fallback to deterministic heuristic extractor
        return self._extract_heuristic_fallback(
            text=text,
            sha256_hash=sha256_hash,
            filename=filename,
            doc_type=doc_type
        )
