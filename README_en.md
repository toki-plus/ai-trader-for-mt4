# AI Trader for MT4

An AI-assisted trading research and controlled-execution framework for MetaTrader 4.

The project combines market-data tools, strategy configuration, risk rules, signal lifecycle, MT4 communication, and LLM-assisted analysis in a traceable desktop application. The design keeps the model inside explicit tool and risk boundaries instead of granting unconstrained trading authority.

> This project is for software-engineering and quantitative-research purposes. It is not investment advice. Validate all automated behavior in demo and isolated environments first.

## Problem Context

Sending market data directly to an LLM and converting the response into an order creates several risks:

- The model may lack account, position, or market context
- Natural-language output does not map reliably to execution actions
- Risk rules can be lost across multiple reasoning cycles
- Order state, exceptions, and historical decisions may not be traceable

This project exposes trading capabilities as structured tools and controls execution through workflows, state management, and deterministic validation.

## Design Goals

- Provide structured rather than fragmented trading context
- Separate read-only analysis, candidate plans, and execution
- Validate position size, stops, order state, and duplicate actions with deterministic rules
- Preserve analysis, tool-call, signal, and execution logs
- Support configurable strategy profiles and model providers

## Architecture

```text
MetaTrader 4
    <-> File-based bridge / compiled EA
        <-> Python application
            -> Market data tools
            -> Portfolio and order tools
            -> Strategy and risk configuration
            -> LLM-assisted agent
            -> Signal and execution workflows
            -> Structured logs and local database
```

## Main Modules

- `src/bridge/`: MT4 communication and AI-client boundaries
- `src/app/`: agent, prompts, trading engine, and application flow
- `src/tools/`: market, portfolio, trading, news, pattern, and workflow tools
- `src/services/`: configuration, logging, database, and order-state management
- `src/gui/`: desktop interface and chart components
- `config/`: model, strategy, and calendar configuration
- `tests/test_integration_suite.py`: integration coverage for trading flows and exception scenarios

Core technologies: Python, PyQt5, asynchronous tasks, LLM APIs, local state/database management, and a MetaTrader 4 EA bridge.

## Workflow

```text
Market and account state
    -> Prepare workflow
    -> Read-only analysis
    -> Candidate trade plan
    -> Deterministic validation
    -> Controlled execution
    -> Position management
    -> Logs and review
```

## Quick Start

### Requirements

- Windows
- MetaTrader 4
- Python 3.8+
- At least one supported LLM API

### Run from Source

```bash
git clone https://github.com/toki-plus/ai-trader-for-mt4.git
cd ai-trader-for-mt4
python -m venv venv
```

After activating the virtual environment, install dependencies and copy the configuration template:

```bash
pip install -r requirements.txt
copy .env.example .env
```

1. Copy `MQL4/Experts/AI_Trader_for_MT4.ex4` to `MQL4/Experts/` under the MT4 data directory.
2. Configure the local `MT4_DATA_PATH` and required API credentials in `.env`.
3. Start MT4 and the EA on a demo account.
4. Run the desktop application:

```bash
python main.py
```

## Validation Guidance

- Begin with connectivity, read-only queries, and logging on a demo account and one symbol.
- Validate position sizing, stops, duplicate-order protection, and recovery rules before enabling execution.
- The integration suite interacts with trading workflows and must run only in an isolated test environment:

```bash
python tests/test_integration_suite.py
```

## Current Limitations

- The MT4 file bridge introduces polling latency and requires the terminal to remain active.
- News and model functions depend on external API availability and quotas.
- Model output is non-deterministic and cannot replace risk rules or human oversight.
- Continuous integration is not configured; tests must be run in a controlled environment.

## Risk Notice

- No return or strategy performance is guaranteed.
- Backtests, simulations, and historical results do not predict future performance.
- Users must understand the software, strategy, broker, and market risks before enabling execution.

## License

See [LICENSE](./LICENSE).
