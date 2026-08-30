from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/thai2d"
    api_token: str = "change-me-internal-token"

    # Walk-forward chronological split fractions.
    wf_train_fraction: float = 0.60
    wf_validation_fraction: float = 0.20

    # Multicollinearity control (spec: FEATURE_CORRELATION_THRESHOLD).
    feature_correlation_threshold: float = 0.90

    # Cold-start data tiers (minimum valid results per tier boundary).
    tier2_min: int = 100
    tier3_min: int = 500
    tier4_min: int = 1000

    # Ensemble / ML controls.
    ml_random_seed: int = 42
    ewf_halflife: int = 30          # exponential-weight halflife in draws
    markov_laplace_alpha: float = 1.0
    max_walkforward_steps: int = 400

    strict_validation: bool = True


settings = Settings()
