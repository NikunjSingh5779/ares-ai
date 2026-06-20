"""Abstract base agent with typed I/O contracts.

Every agent in the system extends this class and implements:
- agent_name: class variable (used in logging and dispatch)
- input_schema / output_schema: Pydantic models defining I/O contracts
- process(): the core execution method

Per AGENT I/O CONTRACTS (see CLAUDE.md):
- Each agent receives a typed state slice and must return a typed output.
- Outputs are validated on receipt. If validation fails, retry once with
  a corrective prompt; if it fails twice, fall back to the next model.
- rationale/explanation fields required wherever the agent produces a
  trading-relevant number.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict


class FlexibleSchema(BaseModel):
    """Fallback schema that accepts any fields.

    Used as the default input_schema/output_schema for agents that
    haven't defined their own yet (e.g., StubAgent). Allows validation
    to succeed for any arbitrary dict input.
    """

    model_config = ConfigDict(extra="allow")


class AgentContext(BaseModel):
    """Standard context passed to every agent execution."""

    session_id: str = ""
    request_id: str = ""
    symbol: str = ""
    timestamp: datetime | None = None
    model_preferences: dict[str, Any] = {}
    retry_count: int = 0

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        if not self.request_id:
            self.request_id = str(uuid.uuid4())
        if self.timestamp is None:
            self.timestamp = datetime.now(UTC)


InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class BaseAgent(ABC, Generic[InputT, OutputT]):
    """Abstract base agent enforcing typed I/O contracts.

    Subclasses must define:
    - agent_name (class variable)
    - input_schema / output_schema (Pydantic model classes)
    - process() method implementing agent logic

    The run() method wraps process() with input validation, output
    validation, execution timing, and structured logging.
    """

    agent_name: str = "base"
    input_schema: type[BaseModel] = FlexibleSchema
    output_schema: type[BaseModel] = FlexibleSchema

    def __init__(self, context: AgentContext | None = None) -> None:
        self.context = context or AgentContext()
        self.execution_log: dict[str, Any] = {
            "agent": self.agent_name,
            "started_at": None,
            "completed_at": None,
            "success": False,
            "error": None,
            "model_used": None,
            "latency_ms": None,
        }

    @abstractmethod
    async def process(self, inputs: InputT) -> OutputT:
        """Execute the agent's core logic.

        Args:
            inputs: Validated input matching input_schema.

        Returns:
            Validated output matching output_schema.
        """
        ...

    def validate_input(self, data: dict[str, Any]) -> InputT:
        """Validate input data against the agent's input schema."""
        return self.input_schema.model_validate(data)

    def validate_output(self, data: dict[str, Any]) -> OutputT:
        """Validate output data against the agent's output schema."""
        return self.output_schema.model_validate(data)

    async def run(self, inputs: InputT | dict[str, Any]) -> OutputT:
        """Full execution lifecycle: validate, execute, validate output, log.

        Handles:
        - Input validation (Pydantic)
        - Execution with timing
        - Output validation (Pydantic)
        - Structured execution logging
        """
        self.execution_log["started_at"] = datetime.now(UTC).isoformat()
        start = time.monotonic()

        # Coerce to InputT if needed
        if isinstance(inputs, dict):
            inputs = self.validate_input(inputs)
        elif not isinstance(inputs, self.input_schema):
            inputs = self.validate_input(inputs.model_dump())

        try:
            outputs = await self.process(inputs)

            # Validate outputs
            if isinstance(outputs, dict):
                outputs = self.validate_output(outputs)
            elif not isinstance(outputs, self.output_schema):
                outputs = self.validate_output(outputs.model_dump())

            elapsed_ms = int((time.monotonic() - start) * 1000)
            self.execution_log.update({
                "completed_at": datetime.now(UTC).isoformat(),
                "success": True,
                "latency_ms": elapsed_ms,
            })
            return outputs

        except Exception as e:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            self.execution_log.update({
                "completed_at": datetime.now(UTC).isoformat(),
                "success": False,
                "error": str(e),
                "latency_ms": elapsed_ms,
            })
            raise


class StubAgent(BaseAgent[InputT, OutputT]):
    """Placeholder agent for future milestones.

    Used in M1 to satisfy the agent pipeline structure without
    implementing actual agent logic. Raises NotImplementedError
    with a clear message about which agent hasn't been built yet.

    To be replaced in M3+ with real agent implementations.
    """

    def __init__(
        self,
        target_agent: str = "unknown",
        context: AgentContext | None = None,
    ) -> None:
        super().__init__(context=context)
        self.target_agent = target_agent
        self.agent_name = f"stub_{target_agent}"

    async def process(self, inputs: InputT) -> OutputT:
        raise NotImplementedError(
            f"[STUB] '{self.target_agent}' agent is not implemented yet. "
            f"Will be built in a future milestone. "
            f"Received inputs: {inputs.model_dump()}"
        )
