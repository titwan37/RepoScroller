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

        # 1. Extract Document Type Node
        if doc_type:
            dt_id = canonicalize_node_id("contract_type", doc_type)
            nodes[dt_id] = EntityNode(
                node_id=dt_id,
                node_type="contract_type",
                name=doc_type.replace("_", " ").title()
            )
            links.append(DocumentEntityLink(sha256_hash=sha256_hash, node_id=dt_id, role="subject_matter"))

        # 2. Extract Signatories / Parties
        sign_patterns = [
            r"(?:Signed by|Signé par|Unterschrift|Signatory|Signature|Signatures)[\s:]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})",
            r"(?:Between|Entre|Zwischen)[\s:]+([A-Z][a-zA-Z0-9\.\s\(\)-]+?)(?:\s*(?:and|et|und|&)|\n)",
            r"(?:Employer|Arbeitgeber|Employeur)[\s:]+([A-Z][a-zA-Z0-9\.\s\(\)-]+?)(?:\n|,|\.)",
            r"(?:Employee|Arbeitnehmer|Employé)[\s:]+([A-Z][a-zA-Z0-9\.\s\(\)-]+?)(?:\n|,|\.)",
            r"(?:Tenant|Landlord|Vermieter|Mieter|Locataire|Bailleur)[\s:]+([A-Z][a-zA-Z0-9\.\s\(\)-]+?)(?:\n|,|\.)",
        ]
        parties_found = set()
        for pat in sign_patterns:
            for match in re.finditer(pat, text, re.IGNORECASE):
                val = match.group(1).strip()
                # Clean trailing roles like (Employer) or (Employee)
                val = re.sub(r'\s*\([^)]*\)', '', val).strip()
                if len(val) > 2 and len(val) < 60 and not any(w in val.lower() for w in ["agreement", "contract", "page", "date"]):
                    parties_found.add(val)

        # Also extract any explicit Organization pattern (e.g. Swisscom AG, UBS Switzerland SA, Acme GmbH)
        org_explicit = re.findall(r'\b([A-Z][A-Za-z0-9\s\.\-&]{1,40}\b(?:AG|SA|GmbH|Sàrl|LLC|Ltd|Inc|Bank|Corp|Court|Kantonsgericht|Bezirksgericht|Steueramt))\b', text)
        for org in org_explicit:
            clean_org = org.strip()
            if len(clean_org) > 2 and not any(w in clean_org.lower() for w in ["agreement", "contract"]):
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

        # 5. Extract Locations (e.g. Zurich, Geneva, Lausanne, Basel, Bern, Tenerife)
        locations = ["Zurich", "Zürich", "Geneva", "Genève", "Lausanne", "Basel", "Bern", "Luzern", "Lugano", "Tenerife", "Paris", "London", "New York"]
        for loc in locations:
            if re.search(r'\b' + re.escape(loc) + r'\b', text, re.IGNORECASE):
                loc_id = canonicalize_node_id("location", loc)
                if loc_id not in nodes:
                    nodes[loc_id] = EntityNode(node_id=loc_id, node_type="location", name=loc)
                links.append(DocumentEntityLink(sha256_hash=sha256_hash, node_id=loc_id, role="mention"))

        # 6. Form edges between extracted parties
        party_node_ids = [n.node_id for n in nodes.values() if n.node_type in ["person", "organization"]]
        for i in range(len(party_node_ids)):
            for j in range(i + 1, len(party_node_ids)):
                edges.append(EntityEdge(
                    source_id=party_node_ids[i],
                    target_id=party_node_ids[j],
                    relation_type="PARTY_TO",
                    properties={"context": f"Co-parties in {filename or sha256_hash[:8]}"}
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
