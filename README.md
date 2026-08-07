# AI Trader for MT4

面向 MetaTrader 4 的 AI 辅助交易研究与受控执行框架。

项目将市场数据工具、策略配置、风险规则、信号生命周期、MT4 通信和大模型分析整合为可追踪的桌面应用。设计重点是让模型在明确工具和风险边界内工作，而不是将交易权限无约束地交给 AI。

> 本项目用于软件工程与量化研究，不构成投资建议。任何自动化交易都应先在模拟账户和隔离环境中验证。

## 项目背景

直接把行情数据交给大模型并生成交易指令，存在几个明显问题：

- 模型可能缺少账户、持仓或市场状态
- 自然语言输出难以稳定映射为执行动作
- 风险规则可能在多轮分析中被忽略
- 订单状态、异常和历史决策缺少可追踪记录

本项目将交易相关能力拆分为结构化工具，并使用流程、状态管理和确定性校验控制执行边界。

## 设计目标

- 为模型提供结构化而非零散的交易上下文
- 将只读分析、候选计划和实际执行分开
- 使用确定性规则检查仓位、止损、订单状态和重复操作
- 保留分析、工具调用、信号与执行日志
- 支持策略配置和模型提供方切换

## 系统架构

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

## 主要模块

- `src/bridge/`：MT4 通信与 AI 客户端边界
- `src/app/`：Agent、提示词、交易引擎与应用流程
- `src/tools/`：行情、组合、交易、新闻、形态与工作流工具
- `src/services/`：配置、日志、数据库与订单状态管理
- `src/gui/`：桌面界面与图表组件
- `config/`：模型、策略和日历配置
- `tests/test_integration_suite.py`：交易流程和异常场景的集成验证

主要技术：Python、PyQt5、异步任务、LLM API、SQLite/本地状态、MetaTrader 4 EA Bridge。

## 工作流程

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

## 快速开始

### 环境要求

- Windows
- MetaTrader 4
- Python 3.8+
- 至少一个受支持的 LLM API

### 从源码运行

```bash
git clone https://github.com/toki-plus/ai-trader-for-mt4.git
cd ai-trader-for-mt4
python -m venv venv
```

激活虚拟环境后安装依赖，并复制配置模板：

```bash
pip install -r requirements.txt
copy .env.example .env
```

1. 将 `MQL4/Experts/AI_Trader_for_MT4.ex4` 复制到 MT4 数据目录下的 `MQL4/Experts/`。
2. 在 `.env` 中配置本地 `MT4_DATA_PATH` 和所需 API 凭据。
3. 在模拟账户中启动 MT4 和 EA。
4. 运行桌面应用：

```bash
python main.py
```

## 验证建议

- 先在模拟账户和单一品种上验证连接、只读查询和日志。
- 在启用任何执行功能前，验证仓位、止损、重复订单和异常恢复规则。
- 集成测试会访问交易流程，必须在隔离的测试环境中运行：

```bash
python tests/test_integration_suite.py
```

## 当前限制

- MT4 文件桥接存在轮询延迟，并依赖终端持续运行。
- 新闻和模型服务依赖外部 API 的可用性与配额。
- 模型输出不具备确定性，不能替代风险规则和人工监督。
- 项目尚未配置持续集成，测试应由使用者在受控环境中执行。

## 风险说明

- 不保证收益或策略表现。
- 回测、模拟和历史结果不代表未来表现。
- 使用者应理解代码、策略、经纪商和市场风险后再决定是否启用执行功能。

## License

See [LICENSE](./LICENSE).
