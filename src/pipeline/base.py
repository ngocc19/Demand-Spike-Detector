"""
Base classes and data contracts for Factor Plugins
===================================================

This module defines the standardized interfaces that all factor plugins
must implement, ensuring consistent data format across the pipeline.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum
import pandas as pd


class FactorType(Enum):
    """Enum defining all available factor types."""
    WEATHER = "weather"
    FLOOD = "flood"
    EVENT = "event"
    HOLIDAY = "holiday"
    AOE_SALE = "aoe_sale"          # Flash sale - Affect-Of-Offer
    CONCERT = "concert"            # Concert/Performance
    SPORT_MATCH = "sport_match"    # Sports event
    NEWS = "news"                  # Breaking news
    TRAFFIC = "traffic"            # Traffic congestion
    POLLUTION = "pollution"        # AQI level


@dataclass
class FactorRecord:
    """
    Standardized data contract - ALL factors must return this format.

    This is the "lingua franca" of the pipeline, ensuring consistency.
    """
    hex_id: str                           # H3 hex ID
    datetime_30min: datetime             # Time slot (aligned to 30 min)
    factor_type: FactorType              # Type of factor
    factor_name: str                     # Specific name: "heavy_rain", "football_match"
    value: float                         # Impact value (0.0 - 1.0 or raw)
    severity: Optional[str] = None       # LOW, MEDIUM, HIGH, SEVERE
    metadata: Dict[str, Any] = field(default_factory=dict)  # Raw data
    confidence: float = 1.0              # Data reliability
    source: str = ""                     # Data source
    ingested_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        """Convert to dict for storage in Feature Store."""
        return {
            "hex_id": self.hex_id,
            "datetime_30min": self.datetime_30min.strftime("%Y-%m-%d %H:%M:%S"),
            "factor_type": self.factor_type.value,
            "factor_name": self.factor_name,
            "value": self.value,
            "severity": self.severity,
            "metadata": str(self.metadata),
            "confidence": self.confidence,
            "source": self.source,
            "ingested_at": self.ingested_at.strftime("%Y-%m-%d %H:%M:%S"),
        }


class BaseFactorPlugin(ABC):
    """
    Abstract Base Class for all Factor Plugins.

    Design Pattern: Template Method + Strategy
    - Template Method: run_pipeline() defines the skeleton
    - Strategy: fetch(), transform(), map_spatial() are implemented per plugin
    """

    # Class variables - override in subclass
    factor_type: FactorType = FactorType.WEATHER
    factor_name: str = "base"
    schedule: str = "0 * * * *"  # Cron format (every hour by default)

    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: Configuration dict from factors.yaml
        """
        self.config = config
        self.raw_data: Optional[pd.DataFrame] = None
        self.processed_data: List[FactorRecord] = []

    @abstractmethod
    def fetch(self) -> pd.DataFrame:
        """
        Step 1: Fetch raw data from source (API, RSS, File, etc.)

        Returns:
            DataFrame with raw data
        """
        pass

    @abstractmethod
    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Step 2: Transform raw data -> clean, normalized format

        Args:
            df: Raw data from fetch()

        Returns:
            DataFrame with cleaned and normalized data
        """
        pass

    @abstractmethod
    def map_spatial(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Step 3: Map location -> H3 hex_id

        Args:
            df: Cleaned data from transform()

        Returns:
            DataFrame with 'hex_id' column added
        """
        pass

    def align_temporal(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Step 4: Align time to 30-minute grid

        Args:
            df: DataFrame with 'datetime' column

        Returns:
            DataFrame with 'datetime_30min' column
        """
        df = df.copy()

        if 'datetime' not in df.columns:
            raise ValueError("DataFrame must have 'datetime' column")

        # Floor to 30-minute grid
        df['datetime_30min'] = df['datetime'].dt.floor('30min')

        return df

    def validate(self, df: pd.DataFrame) -> bool:
        """
        Step 5: Validate output

        Args:
            df: Final DataFrame

        Returns:
            True if valid, raise exception otherwise
        """
        required_cols = ['hex_id', 'datetime_30min', 'value']
        missing = [col for col in required_cols if col not in df.columns]

        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        return True

    def run_pipeline(self) -> List[FactorRecord]:
        """
        Template Method - Pipeline skeleton

        Flow: fetch -> transform -> map_spatial -> align_temporal -> validate -> output
        """
        print(f"[{self.factor_name}] Starting pipeline...")

        # Step 1: Fetch
        self.raw_data = self.fetch()
        print(f"[{self.factor_name}] Fetched {len(self.raw_data)} records")

        # Step 2: Transform
        df = self.transform(self.raw_data)
        print(f"[{self.factor_name}] Transformed to {len(df)} clean records")

        # Step 3: Spatial mapping
        df = self.map_spatial(df)
        print(f"[{self.factor_name}] Mapped to H3 hex_ids")

        # Step 4: Temporal alignment
        df = self.align_temporal(df)

        # Step 5: Validate
        self.validate(df)
        print(f"[{self.factor_name}] Validation passed")

        # Step 6: Convert to FactorRecord
        self.processed_data = self._to_factor_records(df)
        print(f"[{self.factor_name}] Generated {len(self.processed_data)} FactorRecords")

        return self.processed_data

    def _to_factor_records(self, df: pd.DataFrame) -> List[FactorRecord]:
        """Convert DataFrame rows to FactorRecord objects."""
        records = []

        for _, row in df.iterrows():
            record = FactorRecord(
                hex_id=row['hex_id'],
                datetime_30min=row['datetime_30min'],
                factor_type=self.factor_type,
                factor_name=self.factor_name,
                value=row['value'],
                severity=row.get('severity'),
                metadata=row.get('metadata', {}),
                confidence=row.get('confidence', 1.0),
                source=self.config.get('source', ''),
            )
            records.append(record)

        return records

    def get_records_df(self) -> pd.DataFrame:
        """Get processed data as DataFrame for Feature Store insertion."""
        return pd.DataFrame([r.to_dict() for r in self.processed_data])
