from sqlalchemy import Column, Integer, String, JSON, ForeignKey, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import datetime

Base = declarative_base()

class FormTemplate(Base):
    __tablename__ = 'form_templates'
    template_id = Column(Integer, primary_key=True)
    name = Column(String)
    form_type = Column(String)
    version = Column(String)
    schema_json = Column(JSON)
    form_runs = relationship("FormRun", back_populates="form_template")

class FormRun(Base):
    __tablename__ = 'form_runs'
    run_id = Column(Integer, primary_key=True)
    template_id = Column(Integer, ForeignKey('form_templates.template_id'))
    status = Column(String)
    progress = Column(String)
    target_path = Column(String)
    field_runs = relationship("FieldRun", back_populates="form_run")
    form_template = relationship("FormTemplate", back_populates="form_runs")

class FormField(Base):
    __tablename__ = 'form_fields'
    field_id = Column(Integer, primary_key=True)
    template_id = Column(Integer, ForeignKey('form_templates.template_id'))
    label = Column(String)
    canonical_question = Column(String)
    expected_type = Column(String)
    jurisdiction = Column(String)
    validation_rules = Column(JSON)
    field_runs = relationship("FieldRun", back_populates="form_field")

class FieldRun(Base):
    __tablename__ = 'field_runs'
    field_run_id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey('form_runs.run_id'))
    field_id = Column(Integer, ForeignKey('form_fields.field_id'))
    status = Column(String)
    proposed_value = Column(String)
    confidence = Column(Float)
    requires_human_review = Column(Boolean)
    evidence_links = relationship("EvidenceLink", back_populates="field_run")
    form_run = relationship("FormRun", back_populates="field_runs")
    form_field = relationship("FormField", back_populates="field_runs")

class EvidenceLink(Base):
    __tablename__ = 'evidence_links'
    evidence_id = Column(Integer, primary_key=True)
    field_run_id = Column(Integer, ForeignKey('field_runs.field_run_id'))
    chunk_id = Column(String)
    document_hash = Column(String)
    page_number = Column(Integer)
    excerpt = Column(String)
    field_run = relationship("FieldRun", back_populates="evidence_links")

class KnowledgeFact(Base):
    __tablename__ = 'knowledge_facts'
    fact_id = Column(Integer, primary_key=True)
    subject = Column(String)
    predicate = Column(String)
    object_value = Column(String)
    valid_from = Column(DateTime, default=datetime.datetime.utcnow)
    valid_to = Column(DateTime, default=datetime.datetime.utcnow)
    confidence = Column(Float)
    status = Column(String)

class KnowledgeAnswer(Base):
    __tablename__ = 'knowledge_answers'
    answer_id = Column(Integer, primary_key=True)
    question_hash = Column(String)
    canonical_answer = Column(String)
    jurisdiction = Column(String)

class ReviewDecision(Base):
    __tablename__ = 'review_decisions'
    decision_id = Column(Integer, primary_key=True)
    field_run_id = Column(Integer, ForeignKey('field_runs.field_run_id'))
    reviewer = Column(String)
    decision = Column(String)
    comment = Column(String)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    field_run = relationship("FieldRun", back_populates="review_decisions")

class AdminAuditEvent(Base):
    __tablename__ = 'admin_audit_events'
    event_id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey('form_runs.run_id'))
    event_type = Column(String)
    payload = Column(JSON)
    hash = Column(String)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
