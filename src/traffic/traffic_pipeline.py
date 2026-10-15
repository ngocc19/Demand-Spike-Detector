"""
Traffic Prediction Pipeline
=========================

Orchestrator class combining all traffic prediction modules:
    1. TrafficDataGenerator - Generate traffic target from 35 Anchor Points
    2. FeatureEngineer - Merge Weather + Events + Traffic
    3. TrafficPredictor - Train LightGBM model

Usage:
    >>> pipeline = TrafficPredictionPipeline()
    >>> results = pipeline.run_end_to_end(
    ...     weather_df=weather_df,
    ...     events_df=events_df,
    ...     start_date="2024-01-01",
    ...     days=56
    ... )
    >>> metrics = pipeline.evaluate_model()
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from .traffic_data_generator import TrafficDataGenerator
from ..features.feature_engineer import FeatureEngineer
from .traffic_predictor import TrafficPredictor


# =============================================================================
# TRAFFIC PREDICTION PIPELINE
# =============================================================================

class TrafficPredictionPipeline:
    """
    End-to-end orchestrator for traffic prediction.

    Pipeline Flow:
        1. Generate Traffic Target (35 Anchors → 1,960 H3 cells)
        2. Merge Weather + Events + Traffic (safe aggregate)
        3. Train LightGBM Model
        4. Predict & Evaluate

    Attributes:
        data_generator: TrafficDataGenerator instance
        feature_engineer: FeatureEngineer instance
        predictor: TrafficPredictor instance
        training_df: Merged training DataFrame
        predictions: Prediction results DataFrame
    """

    def __init__(
        self,
        models_dir: str = "models",
        seed: int = 42,
    ):
        """
        Initialize TrafficPredictionPipeline.

        Args:
            models_dir: Directory to save/load models
            seed: Random seed for reproducibility
        """
        self.seed = seed
        np.random.seed(seed)

        # Initialize components
        self.data_generator = TrafficDataGenerator()
        self.feature_engineer = FeatureEngineer(seed=seed)
        self.predictor = TrafficPredictor()

        # Output directory
        self.models_dir = Path(models_dir)
        self.models_dir.mkdir(parents=True, exist_ok=True)

        # State tracking
        self.training_df: Optional[pd.DataFrame] = None
        self.predictions: Optional[pd.DataFrame] = None
        self.metrics: Optional[Dict] = None
        self.is_trained: bool = False

    # =========================================================================
    # MAIN PIPELINE METHODS
    # =========================================================================

    def run_end_to_end(
        self,
        weather_df: Optional[pd.DataFrame] = None,
        events_df: Optional[pd.DataFrame] = None,
        start_date: str = "2024-06-29",
        days: int = 56,
        test_ratio: float = 0.2,
        save_model: bool = True,
    ) -> Dict[str, pd.DataFrame]:
        """
        Run complete end-to-end pipeline.

        Steps:
            1. Generate traffic target from 35 Anchor Points
            2. Merge Weather + Events + Traffic
            3. Train LightGBM model
            4. Return results

        Args:
            weather_df: Weather DataFrame (optional, will use mock if None)
            events_df: Events DataFrame (optional, will use mock if None)
            start_date: Start date for traffic generation
            days: Number of days to simulate
            test_ratio: Train/test split ratio
            save_model: Whether to save trained model

        Returns:
            Dictionary with keys: 'training_df', 'predictions', 'metrics'

        Raises:
            ValueError: If required data is missing
        """
        print("=" * 70)
        print("TRAFFIC PREDICTION PIPELINE - END TO END")
        print("=" * 70)

        try:
            # =================================================================
            # STEP 1: Generate Traffic Target
            # =================================================================
            print("\n[Step 1/4] Generating Traffic Target from 35 Anchor Points...")
            traffic_df = self._generate_traffic_target(start_date, days)
            print(f"  -> Generated {len(traffic_df)} traffic records")
            print(f"  -> {traffic_df['h3_index'].nunique()} unique H3 cells")

            # =================================================================
            # STEP 2: Merge Weather + Events + Traffic
            # =================================================================
            print("\n[Step 2/4] Merging Weather + Events + Traffic...")

            # Use mock data if not provided
            if weather_df is None:
                print("  -> Using mock weather data (not provided)")
                weather_df = self._generate_mock_weather(start_date, days)

            if events_df is None:
                print("  -> Using mock events data (not provided)")
                events_df = self._generate_mock_events(start_date, days)

            self.training_df = self.feature_engineer.build_training_data(
                weather_df=weather_df,
                events_df=events_df,
                traffic_df=traffic_df,
            )
            print(f"  -> Merged DataFrame: {len(self.training_df)} rows")

            # Check for row explosion
            assert len(self.training_df) > 0, "Training DataFrame is empty!"

            # =================================================================
            # STEP 3: Train LightGBM Model
            # =================================================================
            print("\n[Step 3/4] Training LightGBM Model...")

            # Check if target exists
            if 'target_traffic_ratio' not in self.training_df.columns:
                raise ValueError(
                    "target_traffic_ratio not found in training data! "
                    "Please ensure traffic_df is properly merged."
                )

            self.metrics = self.predictor.train_model(
                self.training_df,
                test_ratio=test_ratio,
            )

            self.is_trained = True
            print(f"  -> Model trained successfully!")
            print(f"  -> Features: {self.metrics['n_features']}")

            # Save model
            if save_model:
                model_path = self.models_dir / "traffic_model.joblib"
                self.predictor.save_model(str(model_path))
                print(f"  -> Model saved to: {model_path}")

            # =================================================================
            # STEP 4: Generate Predictions
            # =================================================================
            print("\n[Step 4/4] Generating Predictions...")

            self.predictions = self.predictor.predict_next_30m(self.training_df)
            print(f"  -> Generated {len(self.predictions)} predictions")

            # =================================================================
            # RETURN RESULTS
            # =================================================================
            results = {
                'training_df': self.training_df,
                'predictions': self.predictions,
                'metrics': self.metrics,
            }

            print("\n" + "=" * 70)
            print("PIPELINE COMPLETE!")
            print("=" * 70)
            print(f"  Training samples: {self.metrics['train_samples']}")
            print(f"  Test samples: {self.metrics['test_samples']}")
            print(f"  Train RMSE: {self.metrics['train']['rmse']:.4f}")
            print(f"  Test RMSE: {self.metrics['test']['rmse']:.4f}")
            print(f"  Test R2: {self.metrics['test']['r2']:.4f}")

            return results

        except Exception as e:
            print(f"\n[ERROR] Pipeline failed: {e}")
            raise

    def _generate_traffic_target(
        self,
        start_date: str,
        days: int,
    ) -> pd.DataFrame:
        """
        Generate traffic target using TrafficDataGenerator.

        Args:
            start_date: Start date
            days: Number of days

        Returns:
            DataFrame with traffic target
        """
        traffic_df = self.data_generator.generate_dataset(
            start_date=start_date,
            days=days,
            seed=self.seed,
        )

        # Rename columns for consistency
        traffic_df = traffic_df.rename(columns={
            'hex_id': 'h3_index',
        })

        # Ensure datetime column exists (TrafficDataGenerator uses 'timestamp')
        if 'timestamp' in traffic_df.columns and 'datetime' not in traffic_df.columns:
            traffic_df = traffic_df.rename(columns={'timestamp': 'datetime'})

        return traffic_df

    def _generate_mock_weather(
        self,
        start_date: str,
        days: int,
    ) -> pd.DataFrame:
        """
        Generate mock weather data.

        This is used when no real weather data is provided.

        Args:
            start_date: Start date
            days: Number of days

        Returns:
            Mock weather DataFrame
        """
        # Generate timestamps
        start_dt = pd.to_datetime(start_date)
        timestamps = []
        for d in range(days):
            for h in range(24):
                for m in [0, 30]:
                    ts = start_dt + timedelta(days=d, hours=h, minutes=m)
                    timestamps.append(ts)

        # Get H3 hexes from traffic generator
        hexes = self.data_generator.h3_hexes[:min(100, len(self.data_generator.h3_hexes))]

        # Generate weather data
        records = []
        for ts in timestamps:
            for hex_id in hexes:
                records.append({
                    'datetime': ts,
                    'h3_index': hex_id,
                    'temp_c': np.random.normal(30, 5),
                    'humidity_pct': np.random.uniform(60, 95),
                    'precip': np.random.exponential(0.5),
                    'wind_speed': np.random.uniform(5, 20),
                    'cloud_cover': np.random.uniform(0, 100),
                    'pressure': np.random.normal(1013, 10),
                    'weather_impact': np.random.uniform(0, 0.3),
                    'precip_impact': np.random.uniform(0, 0.2),
                    'value': np.random.uniform(0, 0.3),
                })

        return pd.DataFrame(records)

    def _generate_mock_events(
        self,
        start_date: str,
        days: int,
    ) -> pd.DataFrame:
        """
        Generate mock events data.

        This is used when no real events data is provided.

        Args:
            start_date: Start date
            days: Number of days

        Returns:
            Mock events DataFrame
        """
        # Generate random events
        np.random.seed(self.seed)
        n_events = min(500, days * 10)

        start_dt = pd.to_datetime(start_date)

        events = []
        event_types = ['concert', 'festival', 'sport', 'conference', 'cultural']
        event_names = [
            'Music Festival', 'Food Festival', 'Football Match',
            'Tech Conference', 'Art Exhibition', 'Marathon',
            'Street Parade', 'Film Festival', 'Sports Tournament'
        ]

        for _ in range(n_events):
            event_date = start_dt + timedelta(days=np.random.randint(0, days))
            time_slot = f"{np.random.randint(0, 24):02d}:{np.random.choice([0, 30]):02d}"

            # Random location
            lat = 21.0 + np.random.uniform(0, 0.1)
            lon = 105.7 + np.random.uniform(0, 0.2)

            events.append({
                'start_date': event_date.strftime('%d/%m/%y'),
                'time_slot': time_slot,
                'event_name': np.random.choice(event_names),
                'type': np.random.choice(event_types),
                'estimate_attendence': np.random.randint(100, 5000),
                'latitude': lat,
                'longitude': lon,
                'h3_index': f"mock_hex_{np.random.randint(0, 100)}",
            })

        return pd.DataFrame(events)

    # =========================================================================
    # EVALUATION
    # =========================================================================

    def evaluate_model(
        self,
        test_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, float]:
        """
        Evaluate model performance on test set.

        Metrics (following NYC research paper standards):
            - RMSE: Root Mean Square Error
            - R2: Coefficient of Determination

        Args:
            test_df: Test DataFrame (optional, uses training data if None)

        Returns:
            Dictionary with evaluation metrics
        """
        if not self.is_trained:
            raise ValueError("Model not trained yet! Call run_end_to_end() first.")

        if test_df is None:
            # Use stored metrics
            if self.metrics is None:
                raise ValueError("No metrics available! Train model first.")

            return {
                'rmse': self.metrics['test']['rmse'],
                'mae': self.metrics['test']['mae'],
                'r2': self.metrics['test']['r2'],
                'test_samples': self.metrics['test_samples'],
                'train_samples': self.metrics['train_samples'],
            }

        # Calculate metrics on provided test set
        from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

        if 'target_traffic_ratio' not in test_df.columns:
            raise ValueError("test_df must contain 'target_traffic_ratio' column!")

        X_test = test_df.drop(columns=['target_traffic_ratio'])
        y_true = test_df['target_traffic_ratio'].values
        y_pred = self.predictor.predict(X_test)

        rmse = np.sqrt(mean_squared_error(y_true, y_pred))
        mae = mean_absolute_error(y_true, y_pred)
        r2 = r2_score(y_true, y_pred)

        return {
            'rmse': rmse,
            'mae': mae,
            'r2': r2,
            'test_samples': len(test_df),
        }

    def get_feature_importance(self) -> pd.DataFrame:
        """
        Get feature importance from trained model.

        Returns:
            DataFrame with feature names and importance scores
        """
        if not self.is_trained:
            raise ValueError("Model not trained yet!")

        return self.predictor.model.feature_importances_

    # =========================================================================
    # PREDICTION
    # =========================================================================

    def predict(
        self,
        features_df: pd.DataFrame,
        hex_list: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Predict traffic for given features.

        Args:
            features_df: Features DataFrame
            hex_list: List of H3 hex IDs to predict (optional)

        Returns:
            DataFrame with predictions
        """
        if not self.is_trained:
            raise ValueError("Model not trained yet!")

        return self.predictor.predict_next_30m(features_df, hex_list)

    def save_pipeline(self, path: Optional[str] = None):
        """
        Save complete pipeline state.

        Args:
            path: Path to save (optional, uses default)
        """
        import joblib

        path = path or str(self.models_dir / "pipeline_state.joblib")

        artifacts = {
            'predictor_artifacts': {
                'model': self.predictor.model,
                'model_params': self.predictor.model_params,
                'feature_names': self.predictor.feature_names,
                'categorical_features': self.predictor.categorical_features,
                'continuous_features': self.predictor.continuous_features,
            },
            'seed': self.seed,
            'is_trained': self.is_trained,
        }

        joblib.dump(artifacts, path)
        print(f"[Pipeline] Saved to: {path}")

    def load_pipeline(self, path: Optional[str] = None):
        """
        Load pipeline state.

        Args:
            path: Path to load from (optional, uses default)
        """
        import joblib

        path = path or str(self.models_dir / "pipeline_state.joblib")

        artifacts = joblib.load(path)

        self.predictor.model = artifacts['predictor_artifacts']['model']
        self.predictor.model_params = artifacts['predictor_artifacts']['model_params']
        self.predictor.feature_names = artifacts['predictor_artifacts']['feature_names']
        self.predictor.categorical_features = artifacts['predictor_artifacts']['categorical_features']
        self.predictor.continuous_features = artifacts['predictor_artifacts']['continuous_features']
        self.seed = artifacts['seed']
        self.is_trained = artifacts['is_trained']

        print(f"[Pipeline] Loaded from: {path}")

    # =========================================================================
    # SUMMARY
    # =========================================================================

    def get_summary(self) -> Dict:
        """Get pipeline summary."""
        return {
            'is_trained': self.is_trained,
            'models_dir': str(self.models_dir),
            'seed': self.seed,
            'data_generator': {
                'n_anchor_points': len(self.data_generator.h3_hexes),
                'h3_resolution': self.data_generator.h3_resolution,
            },
            'predictor': {
                'n_features': len(self.predictor.feature_names) if self.is_trained else 0,
                'train_samples': self.metrics['train_samples'] if self.metrics else 0,
                'test_samples': self.metrics['test_samples'] if self.metrics else 0,
            },
        }


# =============================================================================
# MAIN - END TO END TEST
# =============================================================================

if __name__ == "__main__":
    import sys

    print("=" * 70)
    print("TRAFFIC PREDICTION PIPELINE - END TO END TEST")
    print("=" * 70)

    # Initialize pipeline
    print("\n[1] Initializing Pipeline...")
    pipeline = TrafficPredictionPipeline(
        models_dir="models",
        seed=42,
    )
    print("  -> Pipeline initialized!")

    # Run end-to-end
    try:
        print("\n[2] Running End-to-End Pipeline...")
        results = pipeline.run_end_to_end(
            weather_df=None,  # Use mock data
            events_df=None,   # Use mock data
            start_date="2026-06-29",
            days=56,  # 8 weeks
            test_ratio=0.2,
            save_model=True,
        )

        # Evaluate
        print("\n[3] Model Evaluation...")
        metrics = pipeline.evaluate_model()
        print("\n  Evaluation Metrics (NYC Research Standard):")
        print(f"  {'='*40}")
        print(f"  | {'Metric':<20} | {'Value':>15} |")
        print(f"  {'-'*40}")
        print(f"  | {'RMSE':<20} | {metrics['rmse']:>15.4f} |")
        print(f"  | {'MAE':<20} | {metrics['mae']:>15.4f} |")
        print(f"  | {'R2 Score':<20} | {metrics['r2']:>15.4f} |")
        print(f"  | {'Test Samples':<20} | {metrics['test_samples']:>15} |")
        print(f"  {'='*40}")

        # Feature importance
        print("\n[4] Top 10 Feature Importance:")
        try:
            importance_df = pipeline.get_feature_importance()
            if isinstance(importance_df, pd.DataFrame) and not importance_df.empty:
                top_features = importance_df.head(10)
                for _, row in top_features.iterrows():
                    print(f"  - {row['feature']}: {row['importance']}")
            elif isinstance(importance_df, np.ndarray):
                print("  (Feature importance available in model)")
        except Exception as e:
            print(f"  (Could not display feature importance: {e})")

        # Sample predictions
        print("\n[5] Sample Predictions:")
        predictions = results['predictions']
        print(predictions.head(10).to_string(index=False))

        # Save pipeline
        print("\n[6] Saving Pipeline State...")
        pipeline.save_pipeline()

        print("\n" + "=" * 70)
        print("TEST COMPLETE!")
        print("=" * 70)
        print("\nNote: This test uses mock data for demonstration.")
        print("For production, provide real weather_df and events_df.")
        print("\nUsage in production:")
        print("  pipeline = TrafficPredictionPipeline()")
        print("  results = pipeline.run_end_to_end(")
        print("      weather_df=real_weather_df,")
        print("      events_df=real_events_df,")
        print("      start_date='2026-06-29',")
        print("      days=56")
        print("  )")

        sys.exit(0)

    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
