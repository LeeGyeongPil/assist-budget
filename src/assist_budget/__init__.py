"""assist-budget: measure and trim what Home Assistant Assist sends to an LLM."""

__version__ = "0.1.1"

# Exit codes shared by the CLI and the tests.
EXIT_OK = 0
EXIT_OVER = 1  # --fail-over and the verdict is "over"
EXIT_INPUT = 2  # bad path, bad plan file, missing optional dependency
EXIT_UNSUPPORTED = 3  # Home Assistant version/format that is not supported
EXIT_CONNECTION = 4  # cannot connect/authenticate, or version outside the write range
EXIT_CONFLICT = 5  # exposure changed since the plan was made
