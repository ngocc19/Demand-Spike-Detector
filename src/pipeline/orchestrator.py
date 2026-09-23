"""
Pipeline Orchestrator
====================

Orchestrates all factor plugins and merges output to Feature Store.
"""

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union
import pandas as pd

from .registry import PluginRegistry
from .base import BaseFactorPlugin, FactorRecord


class PipelineOrchestrator:
    """
    Orchestrates all plugins and writes to Feature Store.

    Key Design:
    - Plugins are loaded dynamically from config
    - No hard-coded plugin names
    - Adding a new factor = adding a config line + plugin file
    """

    def __init__(
        self,
        config_path: str = "config/factors.yaml",
        feature_store_path: str = "data/feature_store.csv"
    ):
        """
        Args:
            config_path: Path to factors.yaml
            feature_store_path: Path to output Feature Store
        """
        self.config_path = config_path
        self.feature_store_path = Path(feature_store_path)

        # Load all plugins from config
        self.plugins: Dict[str, BaseFactorPlugin] = PluginRegistry.load_from_config(config_path)

        # Feature Store cache (in-memory)
        self.feature_store: Optional[pd.DataFrame] = None

        print(f"[Orchestrator] Loaded {len(self.plugins)} plugins: {list(self.plugins.keys())}")

    def run_plugin(self, plugin_name: str) -> pd.DataFrame:
        """
        Run a specific plugin.

        Args:
            plugin_name: Name of the plugin to run

        Returns:
            DataFrame with factor records

        Raises:
            ValueError: If plugin not found in config
        """
        if plugin_name not in self.plugins:
            raise ValueError(
                f"Plugin '{plugin_name}' not found. "
                f"Available plugins: {list(self.plugins.keys())}"
            )

        plugin = self.plugins[plugin_name]

        print(f"\n{'='*60}")
        print(f"Running plugin: {plugin_name}")
        print(f"{'='*60}")

        # Run pipeline
        records = plugin.run_pipeline()

        # Get DataFrame output
        df = plugin.get_records_df()

        print(f"✓ {plugin_name} completed: {len(df)} records")

        return df

    def run_all_plugins(self) -> pd.DataFrame:
        """
        Run all plugins and merge into Feature Store.

        Returns:
            Combined Feature Store DataFrame
        """
        all_dfs = []

        for plugin_name in self.plugins.keys():
            try:
                df = self.run_plugin(plugin_name)
                if not df.empty:
                    all_dfs.append(df)
            except Exception as e:
                print(f"✗ Error running {plugin_name}: {e}")
                # Continue with other plugins
                continue

        if not all_dfs:
            print("Warning: No plugins completed successfully")
            return pd.DataFrame()

        # Concatenate all factor records
        combined_df = pd.concat(all_dfs, ignore_index=True)

        # Pivot to wide format (feature per column)
        feature_store = self._pivot_to_feature_store(combined_df)

        # Save to file
        self._save_feature_store(feature_store)

        return feature_store

    def _pivot_to_feature_store(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Pivot long format -> wide format.

        Input:  hex_id, datetime_30min, factor_name, value
        Output: hex_id, datetime_30min, weather, flood, event, holiday, ...
        """
        if df.empty:
            return pd.DataFrame()

        # Get value column (handle both 'value' and 'weather_impact' etc.)
        value_col = 'value' if 'value' in df.columns else 'weather_impact'

        # Aggregate: take max value if duplicate (multiple factors at same time)
        agg_df = df.groupby(['hex_id', 'datetime_30min', 'factor_name'])[value_col].max().reset_index()

        # Pivot
        pivoted = agg_df.pivot_table(
            index=['hex_id', 'datetime_30min'],
            columns='factor_name',
            values=value_col,
            aggfunc='first'
        ).reset_index()

        # Flatten column names
        pivoted.columns.name = None

        # Fill NaN with 0 (no impact)
        pivoted = pivoted.fillna(0)

        return pivoted

    def _save_feature_store(self, df: pd.DataFrame):
        """Save Feature Store to disk."""
        # Create directory if not exists
        self.feature_store_path.parent.mkdir(parents=True, exist_ok=True)

        # Determine format from extension
        if self.feature_store_path.suffix == '.parquet':
            format = 'parquet'
            mode = 'append'
        else:
            format = 'csv'
            mode = 'overwrite'

        # Append or overwrite
        if self.feature_store_path.exists() and mode == 'append':
            try:
                existing = pd.read_parquet(self.feature_store_path)
                # Merge: update existing, append new
                combined = pd.concat([existing, df]).drop_duplicates(
                    subset=['hex_id', 'datetime_30min'],
                    keep='last'
                )
                self._write_store(combined, format)
                print(f"✓ Updated Feature Store: {len(combined)} total records")
            except Exception:
                # If append fails, overwrite
                self._write_store(df, format)
                print(f"✓ Created Feature Store: {len(df)} records")
        else:
            self._write_store(df, format)
            print(f"✓ Created Feature Store: {len(df)} records")

    def _write_store(self, df: pd.DataFrame, format: str):
        """Write Feature Store to disk."""
        if format == 'parquet':
            df.to_parquet(self.feature_store_path, index=False)
        else:
            df.to_csv(self.feature_store_path, index=False)

    def get_feature_summary(self) -> Dict:
        """Get summary statistics of the Feature Store."""
        if self.feature_store is None:
            if self.feature_store_path.exists():
                if self.feature_store_path.suffix == '.parquet':
                    self.feature_store = pd.read_parquet(self.feature_store_path)
                else:
                    self.feature_store = pd.read_csv(self.feature_store_path)
            else:
                return {}

        summary = {
            'total_records': len(self.feature_store),
            'unique_hexes': self.feature_store['hex_id'].nunique(),
            'date_range': {
                'start': self.feature_store['datetime_30min'].min(),
                'end': self.feature_store['datetime_30min'].max(),
            },
            'factors': {}
        }

        # Factor statistics
        for col in self.feature_store.columns:
            if col not in ['hex_id', 'datetime_30min']:
                non_zero = (self.feature_store[col] > 0).sum()
                summary['factors'][col] = {
                    'total_records': len(self.feature_store),
                    'non_zero_records': int(non_zero),
                    'max_value': float(self.feature_store[col].max()),
                    'mean_value': float(self.feature_store[col].mean()),
                }

        return summary


def run_pipeline():
    """CLI entry point for running the pipeline."""
    import argparse

    parser = argparse.ArgumentParser(description='Run Factor Pipeline')
    parser.add_argument(
        '--config',
        default='config/factors.yaml',
        help='Path to factors.yaml'
    )
    parser.add_argument(
        '--output',
        default='data/feature_store.csv',
        help='Path to output Feature Store'
    )
    parser.add_argument(
        '--plugin',
        help='Run specific plugin only'
    )

    args = parser.parse_args()

    orchestrator = PipelineOrchestrator(
        config_path=args.config,
        feature_store_path=args.output
    )

    if args.plugin:
        df = orchestrator.run_plugin(args.plugin)
    else:
        df = orchestrator.run_all_plugins()

    print("\n" + "="*60)
    print("PIPELINE COMPLETE")
    print("="*60)
    print(f"Total records: {len(df)}")
    print(f"Output: {args.output}")

    return df


if __name__ == '__main__':
    run_pipeline()
