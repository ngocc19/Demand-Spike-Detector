"""
Traffic Predictor Module
======================

LightGBM-based model to predict traffic status for 1,960 H3 cells in Hanoi.

Architecture:
    - Input: Merged DataFrame from FeatureEngineer
    - Target: target_traffic_ratio (0.0-1.0)
    - Model: LightGBM Regressor
    - Output: Traffic prediction for next 30 minutes

Features:
    - Categorical: hex_id, hour, weekday, is_working_day, weather_code,
                   weather_conditions, severity, is_flooded, storm_warning,
                   has_event, event_type, is_holiday, tet_phase
    - Continuous: Lag features, Rolling features, Weather features,
                  Weight features

Usage:
    >>> predictor = TrafficPredictor()
    >>> predictor.train_model(training_df)
    >>> predictions = predictor.predict_next_30m(current_features_df)
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score


# =============================================================================
# CATEGORICAL FEATURE DEFINITIONS
# =============================================================================

CATEGORICAL_FEATURES: List[str] = [
    'hex_id',           # H3 hex ID
    'hour',             # Hour of day (0-23)
    'day_of_week',      # Day of week (2-8)
    'is_working_day',   # 0=non-working, 1=working
    'is_weekend',       # 0=weekday, 1=weekend
    'is_rush_hour',     # 0=normal, 1=rush
    'is_holiday',       # 0=normal, 1=holiday
    'severity',         # LOW, MEDIUM, HIGH, SEVERE
    'has_event',        # 0=no event, 1=has event
    'tet_phase',        # normal, pre_tet, tet_week, post_tet
    'holiday_type',     # solar, lunar, tet, cultural, normal
    'is_monsoon',       # 0=dry, 1=monsoon
]

# Text columns to DROP (free-form text, not for model)
TEXT_COLUMNS_TO_DROP: List[str] = [
    'event_name',       # Free-form text
    'weather_conditions', # Full string description
    'weather_icon',      # Icon name
    'holiday_name',     # Holiday name
    'category',         # Category description
    'region',           # Region text
    'part_of_day',      # morning/afternoon/evening/night
    'anchor_name',      # Anchor point name
    'source',           # Data source name
    'data_version',     # Version string
]

# Features to exclude from model input
EXCLUDED_COLUMNS: List[str] = [
    # Timestamps
    'datetime', 'date', 'fetch_date', 'fetch_timestamp',
    # Target
    'target_traffic_ratio',
    # Metadata
    'anchor_lat', 'anchor_lon',
]


# =============================================================================
# TRAFFIC PREDICTOR CLASS
# =============================================================================

class TrafficPredictor:
    """
    LightGBM-based traffic prediction model.

    Pipeline:
        1. Prepare features (categorical + continuous)
        2. Train model with time-series split
        3. Predict next 30 minutes for all H3 cells

    Attributes:
        model: Trained LightGBM model
        categorical_features: List of categorical feature names
        continuous_features: List of continuous feature names
        feature_names: All feature names used in model
    """

    # LightGBM default parameters (optimized for traffic prediction)
    DEFAULT_PARAMS: Dict = {
        'objective': 'regression',
        'metric': 'rmse',
        'boosting_type': 'gbdt',
        'learning_rate': 0.05,
        'num_leaves': 31,
        'max_depth': 8,
        'min_child_samples': 20,
        'subsample': 0.8,
        'colsample_bytree': 0.7,
        'reg_alpha': 0.1,
        'reg_lambda': 0.1,
        'n_estimators': 500,
        'random_state': 42,
        'verbose': -1,
    }

    def __init__(
        self,
        model_params: Optional[Dict] = None,
        categorical_features: Optional[List[str]] = None,
    ):
        """
        Initialize TrafficPredictor.

        Args:
            model_params: LightGBM parameters (overrides defaults)
            categorical_features: List of categorical feature names
        """
        self.model_params = {**self.DEFAULT_PARAMS, **(model_params or {})}
        self.categorical_features = categorical_features or CATEGORICAL_FEATURES
        self.continuous_features: List[str] = []
        self.feature_names: List[str] = []
        self.model: Optional[lgb.LGBMRegressor] = None

        # Training metadata
        self.train_date_range: Optional[Tuple[str, str]] = None
        self.test_date_range: Optional[Tuple[str, str]] = None

    # =========================================================================
    # DATA PREPARATION
    # =========================================================================

    def _prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Prepare features from merged DataFrame.

        Steps:
        1. Drop excluded columns
        2. Drop text columns
        3. Separate categorical and continuous
        4. Convert categorical to category dtype

        Args:
            df: Merged DataFrame from FeatureEngineer

        Returns:
            DataFrame with prepared features
        """
        df = df.copy()

        # =========================================================================
        # Step 1: Drop excluded columns
        # =========================================================================
        for col in EXCLUDED_COLUMNS:
            if col in df.columns:
                df = df.drop(columns=[col])

        # =========================================================================
        # Step 2: Drop text columns
        # =========================================================================
        for col in TEXT_COLUMNS_TO_DROP:
            if col in df.columns:
                df = df.drop(columns=[col])

        # =========================================================================
        # Step 3: Handle weather_code (if exists)
        # =========================================================================
        if 'owm_weather_code' in df.columns:
            # Convert to categorical
            df['weather_code'] = df['owm_weather_code'].fillna(0).astype(int).astype('category')

        # =========================================================================
        # Step 4: Convert categorical features to category dtype
        # =========================================================================
        for col in self.categorical_features:
            if col in df.columns:
                # Convert to string first to handle mixed types
                df[col] = df[col].astype(str)
                df[col] = df[col].astype('category')

        # =========================================================================
        # Step 5: Identify continuous features
        # =========================================================================
        self.continuous_features = [
            col for col in df.columns
            if col not in self.categorical_features
            and col != 'target_traffic_ratio'
            and pd.api.types.is_numeric_dtype(df[col])
        ]

        # All feature names
        self.feature_names = self.categorical_features + self.continuous_features
        self.feature_names = [f for f in self.feature_names if f in df.columns]

        return df

    def _validate_schema(self, df: pd.DataFrame) -> Tuple[bool, List[str]]:
        """
        Validate that DataFrame has required features.

        Args:
            df: DataFrame to validate

        Returns:
            Tuple of (is_valid, missing_features)
        """
        missing = []

        # Check for datetime
        if 'datetime' not in df.columns:
            missing.append('datetime')

        # Check for target
        if 'target_traffic_ratio' not in df.columns:
            missing.append('target_traffic_ratio')

        # Check for h3_index
        if 'h3_index' not in df.columns and 'hex_id' not in df.columns:
            missing.append('h3_index/hex_id')

        return len(missing) == 0, missing

    # =========================================================================
    # MODEL TRAINING
    # =========================================================================

    def train_model(
        self,
        df: pd.DataFrame,
        test_ratio: float = 0.2,
        early_stopping: bool = True,
    ) -> Dict:
        """
        Train LightGBM model with time-series split.

        CRITICAL: Uses time-based split, NOT random split.
        This prevents data leakage from future to past.

        Args:
            df: Training DataFrame with target_traffic_ratio
            test_ratio: Ratio of data to use for testing (default 0.2)
            early_stopping: Whether to use early stopping

        Returns:
            Dictionary with training metrics
        """
        # =========================================================================
        # Validate schema BEFORE preparing features (which drops datetime)
        # =========================================================================
        is_valid, missing = self._validate_schema(df)
        if not is_valid:
            raise ValueError(f"Missing required columns: {missing}")

        # Store datetime and target for later use (before they're dropped)
        has_datetime = 'datetime' in df.columns
        datetime_series = df['datetime'].copy() if has_datetime else None
        has_target = 'target_traffic_ratio' in df.columns
        target_series = df['target_traffic_ratio'].copy() if has_target else None

        # Sort by datetime for time-series split
        if has_datetime:
            df = df.sort_values('datetime').reset_index(drop=True)

        print("[TrafficPredictor] Preparing features...")
        df = self._prepare_features(df)

        # =========================================================================
        # Time Series Split (NOT random)
        # =========================================================================
        n = len(df)
        split_idx = int(n * (1 - test_ratio))

        train_df = df.iloc[:split_idx].copy()
        test_df = df.iloc[split_idx:].copy()

        # Restore target for training
        if target_series is not None:
            train_df['target_traffic_ratio'] = target_series.iloc[:split_idx].values
            test_df['target_traffic_ratio'] = target_series.iloc[split_idx:].values

        # Restore datetime for date range calculation
        if datetime_series is not None:
            train_df.insert(0, 'datetime', datetime_series.iloc[:split_idx].values)
            test_df.insert(0, 'datetime', datetime_series.iloc[split_idx:].values)

            self.train_date_range = (
                str(train_df['datetime'].min()),
                str(train_df['datetime'].max())
            )
            self.test_date_range = (
                str(test_df['datetime'].min()),
                str(test_df['datetime'].max())
            )
        else:
            self.train_date_range = None
            self.test_date_range = None

        print(f"[TrafficPredictor] Time-series split:")
        print(f"  Train: {self.train_date_range[0]} to {self.train_date_range[1]} ({len(train_df)} rows)")
        print(f"  Test:  {self.test_date_range[0]} to {self.test_date_range[1]} ({len(test_df)} rows)")

        # Prepare features
        X_train = train_df[self.feature_names].copy()
        y_train = train_df['target_traffic_ratio'].values
        X_test = test_df[self.feature_names].copy()
        y_test = test_df['target_traffic_ratio'].values

        # Handle categorical features for LightGBM
        cat_features = [f for f in self.feature_names if f in X_train.columns]
        cat_indices = [X_train.columns.get_loc(f) for f in cat_features]

        # Create LightGBM datasets
        train_data = lgb.Dataset(
            X_train,
            label=y_train,
            categorical_feature=cat_features,
            free_raw_data=False
        )
        test_data = lgb.Dataset(
            X_test,
            label=y_test,
            categorical_feature=cat_features,
            reference=train_data,
            free_raw_data=False
        )

        # =========================================================================
        # Train Model
        # =========================================================================
        print("[TrafficPredictor] Training LightGBM model...")

        # Extract training params
        train_params = {k: v for k, v in self.model_params.items()
                       if k not in ['n_estimators', 'random_state']}

        callbacks = []
        if early_stopping:
            callbacks.append(lgb.early_stopping(stopping_rounds=50))
            callbacks.append(lgb.log_evaluation(period=100))

        # Train
        self.model = lgb.train(
            train_params,
            train_data,
            num_boost_round=self.model_params['n_estimators'],
            valid_sets=[train_data, test_data],
            valid_names=['train', 'test'],
            callbacks=callbacks if callbacks else None,
        )

        # Convert to sklearn-style model for easier prediction
        self.model = lgb.LGBMRegressor(**self.model_params)
        self.model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            callbacks=[lgb.early_stopping(50, verbose=False)] if early_stopping else None,
        )

        # =========================================================================
        # Evaluate
        # =========================================================================
        y_pred_train = self.model.predict(X_train)
        y_pred_test = self.model.predict(X_test)

        metrics = {
            'train': self._compute_metrics(y_train, y_pred_train),
            'test': self._compute_metrics(y_test, y_pred_test),
            'train_samples': len(train_df),
            'test_samples': len(test_df),
            'n_features': len(self.feature_names),
            'feature_importance': self._get_feature_importance(),
        }

        print("[TrafficPredictor] Training complete!")
        print(f"  Train RMSE: {metrics['train']['rmse']:.4f}")
        print(f"  Test RMSE:  {metrics['test']['rmse']:.4f}")
        print(f"  Test R2:    {metrics['test']['r2']:.4f}")

        return metrics

    def _compute_metrics(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray
    ) -> Dict[str, float]:
        """Compute regression metrics."""
        return {
            'rmse': np.sqrt(mean_squared_error(y_true, y_pred)),
            'mae': mean_absolute_error(y_true, y_pred),
            'r2': r2_score(y_true, y_pred),
            'mean_true': float(np.mean(y_true)),
            'mean_pred': float(np.mean(y_pred)),
        }

    def _get_feature_importance(self) -> pd.DataFrame:
        """Get feature importance from trained model."""
        if self.model is None:
            return pd.DataFrame()

        importance = self.model.feature_importances_
        return pd.DataFrame({
            'feature': self.feature_names,
            'importance': importance,
        }).sort_values('importance', ascending=False)

    # =========================================================================
    # PREDICTION
    # =========================================================================

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """
        Predict traffic ratio for given features.

        Args:
            X: DataFrame with same features as training

        Returns:
            Array of predictions (0.0-1.0)
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train_model() first.")

        X = X[self.feature_names].copy()

        # Handle missing categorical values
        for col in self.categorical_features:
            if col in X.columns:
                X[col] = X[col].astype(str).astype('category')

        return self.model.predict(X)

    def predict_next_30m(
        self,
        current_features_df: pd.DataFrame,
        hex_list: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        Predict traffic for next 30 minutes for all H3 cells.

        Args:
            current_features_df: Current features for prediction
            hex_list: List of H3 hex IDs to predict (optional)

        Returns:
            DataFrame with columns: hex_id, predicted_traffic_ratio
        """
        if self.model is None:
            raise ValueError("Model not trained. Call train_model() first.")

        # Filter to specific hexes if provided
        if hex_list is not None:
            df = current_features_df[
                current_features_df['hex_id'].isin(hex_list) |
                current_features_df['h3_index'].isin(hex_list)
            ].copy()
        else:
            df = current_features_df.copy()

        # Remove duplicates (keep latest)
        if 'hex_id' in df.columns:
            df = df.drop_duplicates(subset=['hex_id'], keep='last')
        elif 'h3_index' in df.columns:
            df = df.drop_duplicates(subset=['h3_index'], keep='last')

        # Predict
        predictions = self.predict(df)

        # Clip to valid range
        predictions = np.clip(predictions, 0.0, 1.0)

        # Create output DataFrame
        hex_col = 'hex_id' if 'hex_id' in df.columns else 'h3_index'
        result = pd.DataFrame({
            'hex_id': df[hex_col].values,
            'predicted_traffic_ratio': predictions,
            'prediction_timestamp': datetime.now(),
        })

        return result.sort_values('predicted_traffic_ratio', ascending=False)

    # =========================================================================
    # MODEL PERSISTENCE
    # =========================================================================

    def save_model(self, path: str):
        """Save model to file."""
        import joblib

        artifacts = {
            'model': self.model,
            'model_params': self.model_params,
            'categorical_features': self.categorical_features,
            'continuous_features': self.continuous_features,
            'feature_names': self.feature_names,
            'train_date_range': self.train_date_range,
            'test_date_range': self.test_date_range,
        }

        joblib.dump(artifacts, path)
        print(f"[TrafficPredictor] Model saved to: {path}")

    def load_model(self, path: str):
        """Load model from file."""
        import joblib

        artifacts = joblib.load(path)

        self.model = artifacts['model']
        self.model_params = artifacts['model_params']
        self.categorical_features = artifacts['categorical_features']
        self.continuous_features = artifacts['continuous_features']
        self.feature_names = artifacts['feature_names']
        self.train_date_range = artifacts.get('train_date_range')
        self.test_date_range = artifacts.get('test_date_range')

        print(f"[TrafficPredictor] Model loaded from: {path}")

    # =========================================================================
    # SUMMARY
    # =========================================================================

    def get_summary(self) -> Dict:
        """Get model summary."""
        return {
            'is_trained': self.model is not None,
            'n_features': len(self.feature_names),
            'categorical_features': [f for f in self.feature_names if f in self.categorical_features],
            'continuous_features': self.continuous_features,
            'train_date_range': self.train_date_range,
            'test_date_range': self.test_date_range,
            'model_params': self.model_params,
        }


# =============================================================================
# STANDALONE FUNCTIONS
# =============================================================================

def train_traffic_model(
    df: pd.DataFrame,
    model_params: Optional[Dict] = None,
    test_ratio: float = 0.2,
) -> Tuple[TrafficPredictor, Dict]:
    """
    Convenience function to train traffic model.

    Args:
        df: Training DataFrame
        model_params: LightGBM parameters
        test_ratio: Test split ratio

    Returns:
        Tuple of (TrafficPredictor, metrics dict)
    """
    predictor = TrafficPredictor(model_params=model_params)
    metrics = predictor.train_model(df, test_ratio=test_ratio)
    return predictor, metrics


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("TrafficPredictor - Standalone Test")
    print("=" * 60)

    # Load training data
    print("\n[1] Loading training data...")
    from src.features.feature_engineer import FeatureEngineer

    weather_df = pd.read_parquet('data/weather_anchors_30T_merged.parquet')
    events_df = pd.read_excel('data/event.xlsx')

    # Build training data (without traffic target for now)
    engineer = FeatureEngineer()
    df = engineer.build_training_data(
        weather_df=weather_df,
        events_df=events_df,
        traffic_df=None
    )

    # Add mock target for testing
    # In real scenario, this would come from TrafficDataGenerator
    np.random.seed(42)
    df['target_traffic_ratio'] = np.random.uniform(0.1, 0.8, len(df))

    print(f"    Training data: {len(df)} rows")
    print(f"    Target range: [{df['target_traffic_ratio'].min():.3f}, {df['target_traffic_ratio'].max():.3f}]")

    # Train model
    print("\n[2] Training model...")
    predictor = TrafficPredictor()
    metrics = predictor.train_model(df, test_ratio=0.2)

    # Summary
    print("\n[3] Model Summary:")
    summary = predictor.get_summary()
    for k, v in summary.items():
        if k != 'model_params':
            print(f"    {k}: {v}")

    # Feature importance
    print("\n[4] Top 10 Feature Importance:")
    importance = metrics['feature_importance']
    print(importance.head(10).to_string(index=False))

    # Save model
    print("\n[5] Saving model...")
    predictor.save_model('models/traffic_predictor.joblib')

    print("\n" + "=" * 60)
    print("Test Complete!")
    print("=" * 60)
