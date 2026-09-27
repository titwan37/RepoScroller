"""Entity and relationship extraction engine for building the Document Knowledge Graph."""

import re
import json
import logging
from typing import Dict, Any, List, Optional
import httpx
from reposcroller.config import settings
from reposcroller.ai.graph_schemas import EntityNode, EntityEdge, DocumentEntityLink, DocumentKnowledgeGraph

logger = logging.getLogger("reposcroller.graph_extractor")


def canonicalize_node_id(node_type: str, name: str) -> str:
    """Normalize node ID into a clean canonical slug."""
    clean_name = re.sub(r'[^\w\s-]', '', name.strip().lower())
    clean_name = re.sub(r'[-\s]+', '_', clean_name)
    return f"{node_type}_{clean_name}"


class KnowledgeGraphExtractor:
    """Extracts structured entities, relationships, and document links from document text."""

    def __init__(self, provider: Optional[str] = None):
        self.provider = provider or settings.LLM_PROVIDER

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
            "buchungsanzeige", "mitteilung", "belastung", "gutschrift"
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

        # 2. Extract Signatories / Parties
        sign_patterns = [
            r"(?:Signed by|Signé par|Unterschrift|Signatory|Signature|Signatures)[\s:]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})",
            r"(?:Between|Entre|Zwischen)[\s:]+([A-Z][a-zA-Z0-9\.\s\(\)-]+?)(?:\s*(?:and|et|und|&)|\n)",
            r"(?:Employer|Arbeitgeber|Employeur)[\s:]+([A-Z][a-zA-Z0-9\.\s\(\)-]+?)(?:\n|,|\.)",
            r"(?:Employee|Arbeitnehmer|Employé)[\s:]+([A-Z][a-zA-Z0-9\.\s\(\)-]+?)(?:\n|,|\.)",
            r"(?:Tenant|Landlord|Vermieter|Mieter|Locataire|Bailleur)[\s:]+([A-Z][a-zA-Z0-9\.\s\(\)-]+?)(?:\n|,|\.)",
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
            for match in re.finditer(pat, text, re.IGNORECASE):
                val = match.group(1).strip()
                val = re.sub(r'\s*\([^)]*\)', '', val).strip()
                if is_clean_party(val) and not any(w in val.lower() for w in ["agreement", "contract", "page", "date"]):
                    parties_found.add(val)

        # Also extract any explicit Organization pattern (e.g. Swisscom AG, UBS Switzerland SA, Acme GmbH)
        org_explicit = re.findall(r'\b([A-Z][A-Za-z0-9\s\.\-&]{1,40}\b(?:AG|SA|GmbH|Sàrl|LLC|Ltd|Inc|Bank|Corp|Court|Kantonsgericht|Bezirksgericht|Steueramt))\b', text)
        for org in org_explicit:
            clean_org = org.strip()
            if is_clean_party(clean_org) and not any(w in clean_org.lower() for w in ["agreement", "contract"]):
                parties_found.add(clean_org)

        # 3. Known Company/Institution indicators
        org_indicators = ["AG", "SA", "GmbH", "Sàrl", "LLC", "Ltd", "Inc", "Bank", "Kantonsgericht", "Bezirksgericht", "Steueramt", "Swiss", "Corp", "Court"]
        for p in parties_found:
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

        # 6. Extract Monetary / Value Entities (e.g. CHF 50,000, EUR 12,000, $15,000)
        currency_matches = re.findall(r'\b(CHF|EUR|USD|GBP|€|\$)\s*([0-9]{1,3}(?:[.,\'’]\d{3})*(?:\.\d{2})?)\b', text, re.IGNORECASE)
        for curr, amt in currency_matches[:4]:
            clean_amt = amt.replace("'", "").replace("’", "").replace(",", "")
            try:
                numeric_val = float(clean_amt)
                if numeric_val >= 50:  # Exclude trivial change
                    curr_str = curr.upper() if len(curr) == 3 else ("EUR" if curr == "€" else ("USD" if curr == "$" else "CHF"))
                    amt_label = f"{curr_str} {int(numeric_val):,}"
                    val_id = canonicalize_node_id("monetary_value", amt_label)
                    if val_id not in nodes:
                        nodes[val_id] = EntityNode(
                            node_id=val_id,
                            node_type="monetary_value",
                            name=amt_label,
                            properties={"currency": curr_str, "amount": numeric_val}
                        )
                    links.append(DocumentEntityLink(sha256_hash=sha256_hash, node_id=val_id, role="transaction_value"))
            except ValueError:
                pass

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

        # 9f. Parties & Contract Type -> Monetary Values (VALUED_AT)
        for vid in val_node_ids:
            for pid in party_node_ids:
                edges.append(EntityEdge(
                    source_id=pid,
                    target_id=vid,
                    relation_type="VALUED_AT",
                    weight=1.0,
                    properties={"context": "Financial consideration"}
                ))
            if dt_id and dt_id in nodes:
                edges.append(EntityEdge(
                    source_id=dt_id,
                    target_id=vid,
                    relation_type="VALUED_AT",
                    weight=1.0,
                    properties={"context": "Document financial consideration"}
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

        return DocumentKnowledgeGraph(
            sha256_hash=sha256_hash,
            nodes=list(nodes.values()),
            edges=edges,
            links=links
        )

    def extract_knowledge_graph(self,
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
                prompt = f"""Extract knowledge graph entities and relationships from this document snippet into a strict JSON format.

Document Metadata:
- Filename: {filename}
- Category: {doc_type}
- Date: {doc_date}

Text:
\"\"\"
{text[:2500]}
\"\"\"

Output strictly valid JSON adhering to this schema:
{{
  "entities": [
    {{"type": "person|organization|location|statute", "name": "..."}}
  ],
  "relationships": [
    {{"source": "name1", "target": "name2", "relation": "SIGNS|PARTY_TO|GOVERNED_BY|LOCATED_IN"}}
  ]
}}
Do NOT include preamble or explanations.
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
                        from reposcroller.ai.telemetry import workload_telemetry
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
                        from reposcroller.ai.telemetry import workload_telemetry
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
                            links.append(DocumentEntityLink(sha256_hash=sha256_hash, node_id=node_id, role="mention"))

                    for rel in data.get("relationships", []):
                        s_name = rel.get("source", "").strip()
                        t_name = rel.get("target", "").strip()
                        r_type = rel.get("relation", "PARTY_TO").upper()
                        if s_name and t_name:
                            s_id = canonicalize_node_id("entity", s_name)
                            t_id = canonicalize_node_id("entity", t_name)
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
