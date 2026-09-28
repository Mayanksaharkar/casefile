from datetime import datetime
from typing import Optional, List
from sqlalchemy import Column, String, Integer, DateTime, Boolean, ForeignKey, JSON, Text, Float
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class Requirement(Base):
    """A spec/ticket/acceptance-criterion ingested for a target app."""
    __tablename__ = 'requirements'
    
    id = Column(String, primary_key=True)
    target_app = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False) # e.g., 'PRD', 'Jira', 'manual'
    raw_text = Column(Text, nullable=False)
    parsed_criteria = Column(JSON, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    test_cases = relationship("TestCase", back_populates="requirement")


class TestCase(Base):
    """Generated from a Requirement or from historical exploration."""
    __tablename__ = 'test_cases'
    
    id = Column(String, primary_key=True)
    requirement_id = Column(String, ForeignKey('requirements.id'), nullable=True)
    target_app = Column(String, nullable=False, index=True)
    
    steps = Column(JSON, nullable=False) # Array of structured steps
    expected_result = Column(Text, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    requirement = relationship("Requirement", back_populates="test_cases")


class Run(Base):
    """One audit execution."""
    __tablename__ = 'runs'
    
    id = Column(String, primary_key=True)
    target_url = Column(String, nullable=False)
    repo_path = Column(String, nullable=True)
    
    target_app_version = Column(String, nullable=True)
    trigger_event = Column(String, default="manual") # 'manual', 'ci', 'schedule'
    
    status = Column(String, default="running")
    phase = Column(String, default="starting")
    budget = Column(Integer, default=40)
    
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    config_summary = Column(JSON, nullable=True)
    summary = Column(JSON, nullable=True) # e.g., issue counts
    
    findings = relationship("Finding", back_populates="run", cascade="all, delete-orphan")


class Finding(Base):
    """A single issue surfaced."""
    __tablename__ = 'findings'
    
    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey('runs.id'), nullable=False)
    
    category = Column(String, nullable=False) # 'functional', 'a11y', 'network', 'visual', 'security'
    severity = Column(String, nullable=False) # 'critical', 'high', 'medium', 'low'
    
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    
    confidence_score = Column(Float, nullable=True)
    status = Column(String, default="new") # 'new', 'confirmed', 'false-positive', 'fixed', 'regression'
    
    route = Column(String, nullable=True)
    element_selector = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    run = relationship("Run", back_populates="findings")
    evidence = relationship("Evidence", back_populates="finding", cascade="all, delete-orphan")
    labels = relationship("Label", back_populates="finding", cascade="all, delete-orphan")


class Evidence(Base):
    """Screenshot, DOM snapshot, network trace, video — linked N:1 to Finding."""
    __tablename__ = 'evidence'
    
    id = Column(String, primary_key=True)
    finding_id = Column(String, ForeignKey('findings.id'), nullable=False)
    
    type = Column(String, nullable=False) # 'screenshot', 'dom', 'network', 'console'
    file_path = Column(String, nullable=False) # Path to blob store / local FS
    metadata_json = Column(JSON, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    finding = relationship("Finding", back_populates="evidence")


class FindingDiff(Base):
    """Links a Finding to the prior Run's equivalent (powers regression view)."""
    __tablename__ = 'finding_diffs'
    
    id = Column(String, primary_key=True)
    current_finding_id = Column(String, ForeignKey('findings.id'), nullable=False)
    prior_finding_id = Column(String, ForeignKey('findings.id'), nullable=True)
    
    resolution = Column(String, nullable=False) # 'new', 'recurring', 'fixed'
    
    created_at = Column(DateTime, default=datetime.utcnow)


class Label(Base):
    """Human triage decision on a Finding."""
    __tablename__ = 'labels'
    
    id = Column(String, primary_key=True)
    finding_id = Column(String, ForeignKey('findings.id'), nullable=False)
    
    decision = Column(String, nullable=False) # 'confirm', 'false-positive'
    comment = Column(Text, nullable=True)
    author = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    finding = relationship("Finding", back_populates="labels")


class EvalLog(Base):
    """Minimal eval harness: store every Gemini judgment call."""
    __tablename__ = 'eval_logs'
    
    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey('runs.id'), nullable=False)
    
    prompt = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    parsed_action = Column(JSON, nullable=True)
    
    outcome = Column(String, nullable=True) # Success/Failure of the action taken
    created_at = Column(DateTime, default=datetime.utcnow)


class Fixture(Base):
    """Stores a reusable field answer for the HITL Fixture Vault.
    Values are encrypted at the application layer before reaching this table.
    """
    __tablename__ = 'fixtures'

    id = Column(String, primary_key=True)
    target_app = Column(String, nullable=False, index=True)
    field_key = Column(String, nullable=False)  # CSS selector or label pattern
    value_enc = Column(Text, nullable=False)    # Fernet-encrypted (or base64 fallback)
    field_type = Column(String, default='text') # 'email', 'otp', 'text', 'select', etc.
    vault_type = Column(String, default='ephemeral')  # 'static' | 'ephemeral'
    last_verified = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

