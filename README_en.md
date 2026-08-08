# AI Trader for MT4

[简体中文](./README.md) | [English](./README_en.md)

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
- Support configurable strategy profiles and model providers (OpenAI / DeepSeek / Moonshot, etc.)

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

### Agent Workflow and Rule System

- The AI follows a ReAct-like (Reason + Act) cycle with a strict **`Prepare -> Scan -> Act -> Conclude`** procedure. Every step is grounded in structured tool reports rather than free-form reasoning.
- `prompts.py` defines a system-level rule set: per-trade and portfolio risk caps, position-count limits, signal grading (A/B/C tiers plus an explicit "no-trade" zone), entry rules per pattern, and a profit-ladder strategy for partial take-profits and trailing stops.
- A **Relative Spread Cost** metric lets the AI judge liquidity by spread percentage across asset classes and avoid symbols with prohibitive transaction costs.
- Every Thought, Tool Call, and Observation is recorded and displayed in the GUI for line-by-line review.

### Workflow-Driven Two-Tier Tool System

- **High-level flow tools** (`src/tools/tool_flows.py`): four workflows — `execute_prepare_flow`, `execute_scan_flow`, `execute_trade_flow`, and `execute_management_flow` — wrap dozens of atomic operations into high-level commands, improving decision efficiency while enforcing the standard procedure.
- **Atomic tool layer** (`src/tools/`): 30+ granular tools covering price-action scanning (`scan_for_price_action`), harmonic/supply-demand zone scanning (`scan_for_structures`), dynamic stop-loss calculation from candlestick patterns with an ATR safety buffer (`calculate_stop_loss_from_pattern`), precise risk-based lot sizing (`calculate_lot_size`), and the full set of trade commands including modify and partial close. `search_jina_and_read` lets the AI retrieve relevant news before making decisions.

### MT4–Python Asynchronous Bridge

- The Python backend and the MT4 EA (`AI_Trader_for_MT4.mq4`) communicate by reading and writing `.txt` files under `MQL4/Files`. This producer–consumer design achieves asynchronous decoupling and avoids the fragility of DLL calls.
- The Python side writes command files with unique IDs; the EA polls, executes, and writes matching response files. The EA continuously streams account, position, quote, and candle data, which the Python side monitors in real time.

### Database and State Management

- `src/services/order_db_manager.py` maintains a local SQLite database that mirrors MT4 orders and augments them with structured state.
- AI-opened orders carry a strict `Comment` format — `L=0;G=A;S=PIN;M=N;ID=xxxx` (ladder level / grade / signal type / management state / unique ID) — which the database parses to drive position management.
- When MT4 partially closes an order, it closes the original ticket and opens a new one. The system points the new order's `extends` field at the original and inherits all AI metadata, keeping management logic continuous. Profit-ladder prices (TP1–TP8) are pre-computed at insert time to speed up later decisions.

### PyQt5 GUI

- Built with PyQt5 and qasync (bridging PyQt and asyncio) for a responsive desktop interface showing account equity, open positions, AI status, and thought logs.
- Model and strategy-profile selection plus API-key management are available in the GUI; an integrated pyqtgraph chart viewer opens any symbol's candlestick chart by double-clicking a position.

## 📸 Screenshots

<p align="center">
  <img src="./images/cover_demo.png" alt="Application demo" width="800"/>
  <br>
  <em>Overall runtime demo.</em>
</p>
<p align="center">
  <img src="./images/cover_software_main.png" alt="Main interface" width="800"/>
  <br>
  <em>Main interface: AI agent configuration, strategy selection, account status, and live positions in one view.</em>
</p>
<p align="center">
  <img src="./images/cover_software_log_01.png" alt="AI thought log (1)" width="800"/>
  <br>
  <em>AI thought log: the complete decision chain in real time.</em>
</p>
<p align="center">
  <img src="./images/cover_software_log_02.png" alt="AI thought log (2)" width="800"/>
  <br>
  <em>AI thought log: every tool call and observation is traceable.</em>
</p>
<p align="center">
  <img src="./images/cover_software_chart.png" alt="Chart viewer" width="800"/>
  <br>
  <em>Built-in chart viewer: candlesticks, indicators, and patterns; double-click a position to open its chart.</em>
</p>

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

- Windows (MetaTrader 4 is primarily a Windows platform)
- MetaTrader 4 terminal
- Python 3.8+ (for running from source)
- At least one supported LLM API key (OpenAI / DeepSeek / Moonshot); a Jina API key is optional for news retrieval

### Option 1: Run the Pre-built Package (no Python setup)

1. Download the latest `AI-Trader-For-MT4.zip` from the [Releases page](https://github.com/toki-plus/ai-trader-for-mt4/releases) and extract it.
2. Copy `MQL4/Experts/AI_Trader_for_MT4.mq4` from the extracted folder into `MQL4/Experts/` under the MT4 data directory, refresh Expert Advisors in the Navigator, drag the EA onto a chart, and enable "Allow DLL imports" and "Allow live trading".
3. Copy `.env.example` to `.env` and fill in your API keys. **Critical:** set `MT4_DATA_PATH` to the absolute path of the `MQL4/Files` directory inside the MT4 data folder.
4. Double-click `AI-Trader-For-MT4.exe` to launch.

### Option 2: Run from Source (developers)

```bash
git clone https://github.com/toki-plus/ai-trader-for-mt4.git
cd ai-trader-for-mt4
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Install the EA and configure `.env` as in steps 2–3 of Option 1, then:

```bash
python main.py
```

### Basic Usage

1. Make sure the MT4 terminal is running and the EA is active on a chart (smiley icon in the top-right corner). Start the Python application; the connection indicator in the GUI turns green ("Connected").
2. Select an AI model and a strategy profile in the GUI (e.g., `15-Minute` for intraday cadence, `4-Hour` for swing cadence).
3. Click **RUN** to start the periodic analysis and decision loop. Watch the full reasoning in the "Logs" area and live positions under "MT4 Open Positions". Click **STOP** and the AI finishes its current cycle before stopping safely.

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

## ⚠️ Important Disclaimer

This project is intended for educational and research purposes only. Automated trading systems carry a high level of risk and can result in significant financial losses.

> **It is strongly recommended that you only run this project on a demo account for testing and validation. Do not use it with a live, real-money account.**

- No return or strategy performance is guaranteed; backtests, simulations, and historical results do not predict future performance.
- Users must understand the software, strategy, broker, and market risks before enabling execution.
- The author is not responsible for any financial losses or any other form of loss, direct or indirect, resulting from the use of this software (or any part of it). Running this software on a live account is entirely at your own risk.

## 📂 More Projects

- [video-mover](https://github.com/toki-plus/video-mover) — Automated multi-platform content distribution pipeline: media processing, metadata generation, scheduling, platform adapters
- [ai-highlight-clip](https://github.com/toki-plus/ai-highlight-clip) — Long-video smart triage: Whisper transcription + LLM scoring + human review
- [ai-ttv-workflow](https://github.com/toki-plus/ai-ttv-workflow) — Desktop text-to-video workflow with human-in-the-loop checkpoints
- [ai-video-workflow](https://github.com/toki-plus/ai-video-workflow) — Multi-model AIGC video pipeline orchestrating image, video and music services
- [ai-mixed-cut](https://github.com/toki-plus/ai-mixed-cut) — Video re-creation workflow via structured asset library and script reassembly
- [ai-trader-for-mt5](https://github.com/toki-plus/ai-trader-for-mt5) — AI trading assistant and EA engineering framework for MetaTrader 5
- [auto-usps-tracker](https://github.com/toki-plus/auto-usps-tracker) — Batch shipment tracking and Excel reporting for cross-border e-commerce
- [AB-Video-Deduplicator](https://github.com/toki-plus/AB-Video-Deduplicator) — Experimental video re-creation tool based on high-frame-rate blending
- [netease-downloader](https://github.com/toki-plus/netease-downloader) — Netease Cloud Music desktop downloader: QR login, queue, ID3 tagging

## License

See [LICENSE](./LICENSE).
