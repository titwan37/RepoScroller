"""Pydantic schemas for Knowledge Graph entities, relationships, and document links."""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class EntityNode(BaseModel):
    node_id: str
    node_type: str  # 'person', 'organization', 'location', 'statute', 'contract_type', 'date_event'
    name: str
    properties: Dict[str, Any] = Field(default_factory=dict)

class EntityEdge(BaseModel):
    source_id: str
    target_id: str
    relation_type: str  # 'SIGNS', 'PARTY_TO', 'GOVERNED_BY', 'SUPERSEDES', 'AMENDS', 'REFERENCES', 'LOCATED_IN'
    weight: float = 1.0
    properties: Dict[str, Any] = Field(default_factory=dict)

class DocumentEntityLink(BaseModel):
    sha256_hash: str
    node_id: str
    role: str  # 'signatory', 'counterparty', 'subject_matter', 'governing_law', 'mention'
    confidence: float = 1.0

class DocumentKnowledgeGraph(BaseModel):
    sha256_hash: str
    nodes: List[EntityNode] = Field(default_factory=list)
    edges: List[EntityEdge] = Field(default_factory=list)
    links: List[DocumentEntityLink] = Field(default_factory=list)
