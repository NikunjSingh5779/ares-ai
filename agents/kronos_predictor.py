"""Kronos Market Predictor Agent — ML-powered OHLCV forecasting.

Uses the Kronos foundation model (NeoQuasar/Kronos-small) to predict future
price movements from historical OHLCV data. Kronos is the first open-source
foundation model for financial candlesticks, trained on 45+ global exchanges.

Integration pattern follows MarketAnalystAgent/QuantAgent:
- Typed input/output schemas (Pydantic)
- Falls back gracefully if model unavailable
- Produces a trading signal based on predicted price direction

Model info:
- Kronos-small: 24.7M params, context=512, ~400MB on disk
- Auto-downloaded from HuggingFace on first use
- Requires torch, huggingface_hub, safetensors, einops
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from agents.base import AgentContext, BaseAgent
from agents.state import KronosOutput
from backend.data.ingestor import MarketDataIngestor
from backend.data.models import MarketDataRequest, OHLCVData

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KRONOS_MODEL_ID = "NeoQuasar/Kronos-small"
KRONOS_TOKENIZER_ID = "NeoQuasar/Kronos-Tokenizer-base"
MAX_CONTEXT = 512  # Kronos-small/base context length
DEFAULT_LOOKBACK = 400  # Candles to look back for prediction
DEFAULT_PRED_LEN = 24  # Candles to predict forward


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------
class KronosPredictorInput(BaseModel):
    """Input for the Kronos Market Predictor Agent."""

    symbol: str = Field(..., description="Ticker symbol (e.g. BTC-USD, AAPL)")
    interval: str = Field(default="1d", description="Candle interval")
    lookback: int = Field(default=DEFAULT_LOOKBACK, ge=50, le=MAX_CONTEXT, description="Candles to use as context")
    pred_len: int = Field(default=DEFAULT_PRED_LEN, ge=1, le=120, description="Candles to predict forward")
    candles: list[OHLCVData] | None = Field(
        default=None,
        description="Pre-fetched OHLCV data (bypasses ingestor)",
    )


# ---------------------------------------------------------------------------
# Model wrapper (lazy-loaded singleton)
# ---------------------------------------------------------------------------

class _KronosModel:
    """Lazy singleton wrapper around the Kronos model.

    Loads the model on first call, not at import time. This keeps the
    agent importable even when torch/Kronos is not installed.
    """

    _instance: _KronosModel | None = None
    _loaded: bool = False
    _model: Any = None
    _tokenizer: Any = None
    _predictor: Any = None
    _load_error: str | None = None

    def __new__(cls) -> _KronosModel:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def available(self) -> bool:
        """Whether the model loaded successfully."""
        return self._loaded

    @property
    def load_error(self) -> str | None:
        """Error message from last load attempt."""
        return self._load_error

    def load(self) -> bool:
        """Load model from HuggingFace. Returns True on success."""
        if self._loaded:
            return True

        try:
            import os
            import sys

            import torch

            # Priority: 1) pip-installed version, 2) local kronos_model/ dir,
            #            3) desktop Kronos repo
            kronos_paths = [
                os.path.join(os.path.dirname(__file__), "..", "kronos_model"),
                os.path.join(os.path.dirname(__file__), "..", "Kronos"),
                os.path.join(os.path.dirname(__file__), "..", "..", "..", "..",
                             "OneDrive", "Desktop", "Kronos", "model"),
            ]
            for kp in kronos_paths:
                kp = os.path.abspath(kp)
                if os.path.isdir(kp) and kp not in sys.path:
                    sys.path.insert(0, kp)

            # Try pip-installed first, then local module
            try:
                from kronos.model import Kronos, KronosTokenizer, KronosPredictor  # noqa: I001  # try/except fallback pattern
            except ImportError:
                from model import Kronos, KronosTokenizer, KronosPredictor  # noqa: I001  # fallback import

            device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info(
                "Loading Kronos model from HuggingFace",
                extra={"model": KRONOS_MODEL_ID, "device": device},
            )

            self._tokenizer = KronosTokenizer.from_pretrained(KRONOS_TOKENIZER_ID)
            self._model = Kronos.from_pretrained(KRONOS_MODEL_ID)
            self._model.to(device)
            self._model.eval()

            self._predictor = KronosPredictor(self._model, self._tokenizer, max_context=MAX_CONTEXT)

            self._loaded = True
            logger.info("Kronos model loaded successfully", extra={"device": device})
            return True

        except ImportError as e:
            self._load_error = (
                f"Kronos dependencies not installed: {e}. "
                "Install with: pip install torch huggingface_hub safetensors einops"
            )
            logger.warning(self._load_error)
            return False

        except Exception as e:
            self._load_error = f"Failed to load Kronos model: {e}"
            logger.error(self._load_error, exc_info=True)
            return False


# ---------------------------------------------------------------------------
# Prediction logic
# ---------------------------------------------------------------------------

def _prepare_dataframe(candles: list[OHLCVData]) -> Any:
    """Convert OHLCV candles to the pandas DataFrame format Kronos expects."""
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas is required for Kronos predictor")

    data = []
    for c in candles:
        row = {
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": getattr(c, "volume", 0) or 0,
        }
        data.append(row)

    df = pd.DataFrame(data)
    # Ensure columns in the right order
    for col in ["open", "high", "low", "close", "volume"]:
        if col not in df.columns:
            df[col] = 0.0

    return df


def _make_timestamps(candles: list[OHLCVData], pred_len: int) -> tuple[Any, Any]:
    """Create x_timestamp and y_timestamp pandas Series for Kronos."""
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas is required for Kronos predictor")

    x_ts = pd.Series([c.timestamp for c in candles], name="timestamps")

    # Generate future timestamps based on interval
    if len(candles) < 2:
        # Estimate interval from first candle
        delta = pd.Timedelta(hours=1)
    else:
        delta = candles[-1].timestamp - candles[-2].timestamp
        if delta.total_seconds() <= 0:
            delta = pd.Timedelta(hours=1)

    last_ts = candles[-1].timestamp
    future_ts = [last_ts + delta * (i + 1) for i in range(pred_len)]
    y_ts = pd.Series(future_ts, name="timestamps")

    return x_ts, y_ts


def _analysis_from_prediction(
    symbol: str,
    candles: list[OHLCVData],
    pred_df: Any,
) -> dict[str, Any]:
    """Convert Kronos prediction DataFrame into a structured analysis result.

    Compares the predicted close prices to recent historical close prices
    to determine direction and confidence.
    """
    # Extract predicted values
    pred_closes = pred_df["close"].values if hasattr(pred_df, "values") else [getattr(r, "close", 0) for r in pred_df]

    # Get recent actual closes for comparison
    actual_closes = [c.close for c in candles[-20:]] if len(candles) >= 20 else [c.close for c in candles]

    # Calculate prediction direction
    current_price = actual_closes[-1] if actual_closes else pred_closes[0]
    predicted_final = pred_closes[-1] if len(pred_closes) > 0 else current_price

    # Predicted change percentage
    predicted_change_pct = ((predicted_final - current_price) / current_price) * 100 if current_price > 0 else 0

    # Predicted trend (check if predictions are consistently directional)
    if len(pred_closes) >= 3:
        first_half_avg = np.mean(pred_closes[: len(pred_closes) // 2])
        second_half_avg = np.mean(pred_closes[len(pred_closes) // 2 :])
        trend_direction = "bullish" if second_half_avg > first_half_avg else "bearish"
    else:
        trend_direction = "bullish" if predicted_change_pct > 0 else "bearish"

    # Direction for trading signal
    abs_change = abs(predicted_change_pct)
    if abs_change < 0.5:
        direction = "flat"
        confidence = max(20, abs_change * 20)
    elif predicted_change_pct > 0:
        direction = "long"
        confidence = min(30 + abs_change * 3, 85)
    else:
        direction = "short"
        confidence = min(30 + abs_change * 3, 85)

    # Volatility estimate from prediction range
    pred_range = (max(pred_closes) - min(pred_closes)) / current_price * 100 if current_price > 0 else 0

    return {
        "confidence": round(float(confidence), 1),
        "direction": direction,
        "bias": trend_direction,
        "predicted_prices": [round(float(p), 4) for p in pred_closes],
        "predicted_change_pct": round(float(predicted_change_pct), 2),
        "predicted_range_pct": round(float(pred_range), 2),
        "current_price": round(float(current_price), 4),
        "model_used": KRONOS_MODEL_ID,
        "rationale": (
            f"Kronos model predicts {direction} direction over {len(pred_closes)} periods "
            f"({predicted_change_pct:+.2f}% change). "
            f"Trend: {trend_direction}. Range: {pred_range:.2f}%."
        ),
    }


# ---------------------------------------------------------------------------
# KronosPredictorAgent
# ---------------------------------------------------------------------------
class KronosPredictorAgent(BaseAgent[KronosPredictorInput, KronosOutput]):
    """Market prediction agent powered by the Kronos foundation model.

    Uses a pre-trained Transformer model trained on 45+ global exchanges
    to predict future OHLCV values. Provides a trading signal based on
    predicted price direction.

    Two-tier operation:
    1. If Kronos model loads successfully -> ML-powered prediction
    2. If model unavailable -> simple trend extrapolation fallback

    Usage:
        agent = KronosPredictorAgent(ingestor=ingestor)
        result = await agent.run(KronosPredictorInput(symbol="BTC-USD"))
    """

    agent_name: str = "kronos_predictor"
    input_schema: type[BaseModel] = KronosPredictorInput
    output_schema: type[BaseModel] = KronosOutput

    def __init__(
        self,
        ingestor: MarketDataIngestor | None = None,
        context: AgentContext | None = None,
    ) -> None:
        super().__init__(context=context)
        self.ingestor = ingestor
        self._model_wrapper = _KronosModel()

    async def process(self, inputs: KronosPredictorInput) -> dict[str, Any]:  # type: ignore[override]
        """Execute Kronos-based market prediction.

        1. Fetch/validate OHLCV data
        2. Attempt ML prediction with Kronos model
        3. Fall back to simple trend extrapolation
        4. Return structured result
        """
        # Step 1: Get candle data
        candles = await self._get_candles(inputs)
        if not candles:
            return self._empty_result(f"No market data available for {inputs.symbol}")

        # Trim to lookback
        if len(candles) > inputs.lookback:
            candles = candles[-inputs.lookback :]

        # Require minimum data
        if len(candles) < 50:
            return self._empty_result(f"Insufficient data ({len(candles)} candles, need 50+)")

        # Step 2: Try Kronos model
        try:
            result = await self._predict_with_kronos(candles, inputs)
            if result is not None:
                return result
        except Exception as e:
            logger.error(f"Kronos prediction failed: {e}", exc_info=True)

        # Step 3: Fallback
        return self._trend_fallback(candles)

    async def _get_candles(self, inputs: KronosPredictorInput) -> list[OHLCVData]:
        """Get OHLCV data — either pre-fetched or via ingestor."""
        if inputs.candles:
            return inputs.candles
        if self.ingestor is not None:
            try:
                request = MarketDataRequest(
                    symbol=inputs.symbol,
                    source="yahoo",
                    interval=inputs.interval,
                    limit=inputs.lookback + 50,  # Extra buffer
                )
                result = await self.ingestor.ingest(request)
                return result.candles
            except Exception as e:
                logger.error(f"Failed to fetch candles: {e}", exc_info=True)
                return []
        return []

    async def _predict_with_kronos(
        self,
        candles: list[OHLCVData],
        inputs: KronosPredictorInput,
    ) -> dict[str, Any] | None:
        """Run Kronos model prediction. Returns None if model unavailable."""
        # Ensure model is loaded
        if not self._model_wrapper.load():
            return None

        try:
            # Prepare data
            df = _prepare_dataframe(candles)
            x_ts, y_ts = _make_timestamps(candles, inputs.pred_len)

            # Run prediction
            pred_df = self._model_wrapper._predictor.predict(
                df=df,
                x_timestamp=x_ts,
                y_timestamp=y_ts,
                pred_len=inputs.pred_len,
                T=1.0,
                top_p=0.9,
                sample_count=1,
            )

            # Convert to analysis
            return _analysis_from_prediction(inputs.symbol, candles, pred_df)

        except Exception as e:
            logger.error(f"Kronos prediction runtime error: {e}", exc_info=True)
            return None

    def _trend_fallback(self, candles: list[OHLCVData]) -> dict[str, Any]:
        """Simple trend-based fallback when Kronos model is unavailable."""
        closes = [c.close for c in candles]
        if len(closes) < 20:
            return self._empty_result("Insufficient data for trend fallback")

        # Linear regression on recent closes
        import numpy as np

        recent = closes[-20:]
        x = np.arange(len(recent))
        try:
            slope = np.polyfit(x, recent, 1)[0]
        except np.linalg.LinAlgError:
            slope = 0

        current_price = closes[-1]
        change_pct = (slope * len(recent) / current_price) * 100 if current_price > 0 else 0

        if abs(change_pct) < 0.5:
            direction = "flat"
            confidence = 25.0
            bias = "neutral"
        elif change_pct > 0:
            direction = "long"
            confidence = min(35 + abs(change_pct) * 2, 70)
            bias = "bullish"
        else:
            direction = "short"
            confidence = min(35 + abs(change_pct) * 2, 70)
            bias = "bearish"

        # Simple prediction: extend the slope
        predicted_closes = []
        for i in range(1, 25):
            predicted_closes.append(float(closes[-1] + slope * i))

        return {
            "confidence": round(confidence, 1),
            "direction": direction,
            "bias": bias,
            "predicted_prices": predicted_closes,
            "predicted_change_pct": round(float(change_pct) * 1.5, 2),
            "predicted_range_pct": round(float(abs(slope) * 20 / current_price * 100) if current_price > 0 else 0, 2),
            "current_price": round(float(current_price), 4),
            "model_used": "trend_fallback",
            "rationale": (
                f"Trend fallback (Kronos model unavailable): Linear trend over 20 periods "
                f"predicts {direction} ({change_pct:+.2f}% change). "
                f"Install Kronos deps for ML-powered predictions."
            ),
        }

    def _empty_result(self, reason: str) -> dict[str, Any]:
        """Return an empty/error result."""
        return {
            "confidence": 0.0,
            "direction": "flat",
            "bias": "neutral",
            "predicted_prices": [],
            "predicted_change_pct": 0.0,
            "predicted_range_pct": 0.0,
            "current_price": 0.0,
            "model_used": "none",
            "rationale": reason,
        }
