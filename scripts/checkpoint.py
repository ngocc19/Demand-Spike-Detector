"""
Checkpoint Manager
=================

State management for resumable weather backfill.
Saves progress to JSON file to allow resume after crash/interruption.

Usage:
    from checkpoint import CheckpointManager
    checkpoint = CheckpointManager('data/checkpoint.json')

    # Get resume point
    resume_state = checkpoint.get_resume_state()

    # Update progress
    checkpoint.update_progress(date='2026-07-15', anchor='CauGiay', records_used=850)

    # Check quota
    if checkpoint.is_quota_exceeded('key1'):
        checkpoint.switch_to_next_key()
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CheckpointState:
    """Checkpoint state data structure."""
    last_date: str = ""
    last_anchor: str = ""
    completed_anchors: List[str] = field(default_factory=list)
    remaining_anchors: List[str] = field(default_factory=list)
    daily_quotas: Dict[str, int] = field(default_factory=dict)
    current_key_index: int = 0
    last_updated: str = ""
    total_records_fetched: int = 0
    total_days_completed: int = 0
    status: str = "running"  # running, completed, error

    # Anchor locations data (persisted)
    anchor_data: Dict[str, Dict] = field(default_factory=dict)

    # API keys status
    key_status: Dict[str, str] = field(default_factory=dict)  # active, exhausted, error


class CheckpointManager:
    """
    Manages checkpoint state for resumable backfill operations.

    Features:
    - Auto-save after each API call
    - Resume from exact last position
    - Track API quota per key
    - Detect and handle quota exhaustion
    """

    # Maximum records per key per day
    QUOTA_LIMIT = 1000
    # Default anchors
    DEFAULT_ANCHORS = [
        {"name": "HoanKiem", "lat": 21.0285, "lon": 105.8542},
        {"name": "CauGiay", "lat": 21.0306, "lon": 105.7925},
        {"name": "HoangMai", "lat": 20.9723, "lon": 105.8454},
        {"name": "LongBien", "lat": 21.0470, "lon": 105.8920},
        {"name": "TayHo", "lat": 21.0664, "lon": 105.8176},
        {"name": "NoiBai", "lat": 21.2187, "lon": 105.8042},
    ]

    def __init__(self, checkpoint_path: str = "data/checkpoint.json", anchors: List[Dict] = None):
        """
        Initialize checkpoint manager.

        Args:
            checkpoint_path: Path to checkpoint JSON file
            anchors: List of anchor point dictionaries
        """
        self.checkpoint_path = Path(checkpoint_path)
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

        # Use provided anchors or defaults
        self.anchors = anchors or self.DEFAULT_ANCHORS

        # Load or create state
        self.state = self._load_or_create_state()

        logger.info(f"Checkpoint manager initialized: {checkpoint_path}")
        logger.info(f"Anchors: {[a['name'] for a in self.anchors]}")
        logger.info(f"Current key index: {self.state.current_key_index}")

    def _load_or_create_state(self) -> CheckpointState:
        """Load existing state or create new one."""
        if self.checkpoint_path.exists():
            try:
                with open(self.checkpoint_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                state = CheckpointState(**data)
                logger.info(f"Loaded checkpoint: last_date={state.last_date}, last_anchor={state.last_anchor}")
                return state
            except Exception as e:
                logger.warning(f"Failed to load checkpoint: {e}. Creating new one.")

        # Create new state
        state = CheckpointState(
            completed_anchors=[],
            remaining_anchors=[a['name'] for a in self.anchors],
            daily_quotas={},
            anchor_data={a['name']: a for a in self.anchors},
            key_status={}
        )
        self._save_state(state)
        return state

    def _save_state(self, state: CheckpointState = None):
        """Save state to checkpoint file."""
        if state is None:
            state = self.state

        state.last_updated = datetime.now().isoformat()

        try:
            with open(self.checkpoint_path, 'w', encoding='utf-8') as f:
                json.dump(asdict(state), f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save checkpoint: {e}")
            raise

    def get_resume_state(self) -> Dict[str, Any]:
        """
        Get the resume state for continuing backfill.

        Returns:
            Dictionary with resume information
        """
        return {
            'start_date': self.state.last_date,
            'start_anchor': self.state.last_anchor,
            'completed_anchors': self.state.completed_anchors,
            'remaining_anchors': self.state.remaining_anchors,
            'current_key_index': self.state.current_key_index,
            'daily_quotas': self.state.daily_quotas,
            'total_records_fetched': self.state.total_records_fetched,
            'status': self.state.status
        }

    def update_progress(self, date: str, anchor: str, records_used: int = 1):
        """
        Update progress after fetching data.

        Args:
            date: Current date being processed
            anchor: Current anchor being processed
            records_used: Number of records fetched
        """
        self.state.last_date = date
        self.state.last_anchor = anchor
        self.state.total_records_fetched += records_used

        # Check if anchor is completed
        if anchor not in self.state.completed_anchors:
            self.state.completed_anchors.append(anchor)

        if anchor in self.state.remaining_anchors:
            self.state.remaining_anchors.remove(anchor)

        self._save_state()

        logger.debug(f"Progress updated: date={date}, anchor={anchor}, records={records_used}")

    def increment_quota(self, key: str, count: int = 1):
        """
        Increment quota usage for a key.

        Args:
            key: Key identifier (e.g., "key1")
            count: Number of records to add
        """
        if key not in self.state.daily_quotas:
            self.state.daily_quotas[key] = 0

        self.state.daily_quotas[key] += count
        self._save_state()

        # Log warning if approaching limit
        if self.state.daily_quotas[key] >= self.QUOTA_LIMIT * 0.9:
            logger.warning(f"Key {key} quota at {self.state.daily_quotas[key]}/{self.QUOTA_LIMIT} (90%)")

    def is_quota_exceeded(self, key: str) -> bool:
        """Check if key quota is exceeded."""
        return self.state.daily_quotas.get(key, 0) >= self.QUOTA_LIMIT

    def get_current_quota(self, key: str) -> int:
        """Get current quota usage for a key."""
        return self.state.daily_quotas.get(key, 0)

    def get_remaining_quota(self, key: str) -> int:
        """Get remaining quota for a key."""
        return max(0, self.QUOTA_LIMIT - self.get_current_quota(key))

    def set_key_status(self, key: str, status: str):
        """
        Set status for a key.

        Args:
            key: Key identifier
            status: Status (active, exhausted, error)
        """
        self.state.key_status[key] = status
        self._save_state()

    def get_active_keys(self) -> List[str]:
        """Get list of active (non-exhausted) keys."""
        return [k for k, v in self.state.key_status.items() if v != 'exhausted']

    def reset_daily_quotas(self):
        """Reset all daily quotas (call at start of new day)."""
        self.state.daily_quotas = {}
        for key in self.state.key_status:
            self.state.key_status[key] = 'active'
        self.state.current_key_index = 0
        self._save_state()
        logger.info("Daily quotas reset")

    def reset_all(self):
        """Reset all state to start fresh."""
        self.state = CheckpointState(
            completed_anchors=[],
            remaining_anchors=[a['name'] for a in self.anchors],
            daily_quotas={},
            current_key_index=0,
            anchor_data={a['name']: a for a in self.anchors},
            key_status={}
        )
        self._save_state()
        logger.info("Checkpoint reset to initial state")

    def mark_completed(self):
        """Mark backfill as completed."""
        self.state.status = "completed"
        self._save_state()
        logger.info("Backfill marked as completed")

    def is_completed(self) -> bool:
        """Check if backfill is completed."""
        return self.state.status == "completed"

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of current state."""
        return {
            'status': self.state.status,
            'last_date': self.state.last_date,
            'last_anchor': self.state.last_anchor,
            'anchors_completed': len(self.state.completed_anchors),
            'anchors_remaining': len(self.state.remaining_anchors),
            'total_records_fetched': self.state.total_records_fetched,
            'quota_usage': self.state.daily_quotas,
            'last_updated': self.state.last_updated
        }

    def __repr__(self):
        summary = self.get_summary()
        return f"CheckpointManager({summary['status']}, records={summary['total_records_fetched']}, quota={summary['quota_usage']})"
