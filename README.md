# AI-Trader-For-MT4: LLM驱动的自主型MT4交易机器人框架

[简体中文](./README.md) | [English](./README_en.md)

[![GitHub stars](https://img.shields.io/github/stars/toki-plus/ai-trader-for-mt4?style=social)](https://github.com/toki-plus/ai-trader-for-mt4/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/toki-plus/ai-trader-for-mt4?style=social)](https://github.com/toki-plus/ai-trader-for-mt4/network/members)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/toki-plus/ai-trader-for-mt4/pulls)
[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)

**`AI-Trader-For-MT4` 是一款革命性的、开源的AI交易解决方案，它通过赋予大语言模型（LLM）一套“交易法则”和完备的工具集，将LLM从一个对话工具转变为一个能够独立在 MetaTrader 4 (MT4) 平台上进行“感知-思考-行动”的自主交易代理（Agent）。**

本项目旨在为量化交易者、策略研究员和开发者提供一个终极框架，让您能够将自己复杂的交易哲学、风控纪律和操作流程，通过高度结构化的Prompt“灌输”给AI，并由AI严格、自主地执行。它彻底摆脱了传统EA编程的束缚，进入一个通过自然语言定义和迭代交易策略的全新范式。

<p align="center">
  <a href="https://www.bilibili.com/video/BV1gVrhBgE6L/" target="_blank">
    <img src="./images/cover_demo.png" alt="点击观看B站演示视频（暂未录制）" width="800"/>
  </a>
  <br>
  <em>(点击封面图跳转到 B 站观看高清演示视频)</em>
</p>

---

## ✨ 核心功能

本项目通过五大模块的精密协作，构建了一个真正意义上的AI自主交易生态：

### 🧠 宗师级AI交易员 (Grandmaster AI Trader)

-   **Agentic 工作流**: AI遵循一套类ReAct（Reason + Act）的思考模式，严格按照 **`Prepare -> Scan -> Act -> Conclude`** 的标准作业程序（SOP）进行循环。每一步都依赖于工具返回的结构化报告，而非凭空想象。
-   **“交易法则”系统**: `prompts.py` 中定义了一套极其详尽的系统级指令，堪称AI的“交易法则”。它包含了：
    -   **核心哲学**: 如“生存第一，盈利第二”、“三周期共振”等。
    -   **绝对法则**: 如单笔2%最大风险、组合9%最大风险、最多10个持仓等铁律。
    -   **流动性审查**: 独创的**相对价差成本 (`Relative Spread Cost`)** 概念，让AI能根据不同资产类别（如主流外汇、贵金属、加密货币）的价差百分比，智能判断市场流动性，规避高交易成本陷阱。
    -   **信号评级系统**: 将潜在交易机会严格划分为A、B、C三等，并明确“无交易”区域，杜绝低质量出手。
    -   **精细化执行指令**: 对不同信号（如Pin Bar的挂单入场 vs. Inside Bar的突破入场）有不同的执行细则。
    -   **利润阶梯管理**: 内置一套完整的仓位管理策略，用于分批止盈和移动止损。
-   **多模型兼容**: 在 `config/mt4_config.json` 中可轻松切换 **OpenAI (GPT-4o)**, **DeepSeek**, **Moonshot (Kimi)** 等多种LLM，为您的AI交易员选择不同风格的“大脑”。
-   **完全透明的决策日志**: AI的每一步**思考（Thought）**、**工具调用（Tool Calls）**和**观察（Observation）**都被完整记录并展示在GUI中，让您能深入复盘AI的每一个决策细节。

### 🛠️ 工作流驱动的二级工具系统 (Workflow-Driven Two-Tier Tool System)

-   **高级工作流工具 (`Flow Tools`)**: 位于 `src/tools/tool_flows.py`，这是AI主要的交互接口。`execute_prepare_flow`, `execute_scan_flow`, `execute_trade_flow`, `execute_management_flow` 四大工作流将数十个原子操作封装成高级指令，极大地提高了AI决策效率，并强制其遵循SOP。
-   **全面的原子工具 (`Atomic Tools`)**: 位于 `src/tools/` 各文件中，提供了超过30个精细化的底层工具，涵盖：
    -   **市场分析与形态识别**: 从基础的K线获取，到自动化的**价格行为扫描** (`scan_for_price_action`) 和**谐波/供需区扫描** (`scan_for_structures`)。
    -   **动态止损计算**: 核心工具 `calculate_stop_loss_from_pattern` 可根据不同信号类型（Pin Bar, Engulfing, Zone等）的K线形态，动态计算出最合理的止损位置，并内置**ATR安全缓冲**，防止止损过窄。
    -   **精准仓位计算**: `calculate_lot_size` 工具能根据给定的风险金额、止损距离和品种合约信息，精确计算出符合风控要求的交易手数。
    -   **全功能交易接口**: 封装了从开仓到平仓、从修改到部分平仓的所有MT4交易指令。
    -   **新闻驱动决策**: `search_jina_and_read` 工具允许AI在做出交易决策前，主动搜索并分析相关新闻，将宏观情绪纳入考量。

### 🌉 鲁棒的MT4-Python异步桥接 (Robust MT4-Python Async Bridge)

-   **文件I/O通信机制**: Python后端与MT4 EA (`AI_Trader_for_MT4.mq4`) 之间通过在 `MQL4/Files` 目录下读写一系列`.txt`文件进行通信。这种**生产者-消费者模式**实现了完全的**异步解耦**，避免了DLL调用的脆弱性和复杂性，即使在高频读写下也极为稳定。
-   **命令与响应系统**: Python端生成带唯一ID的命令文件（如`AI_Commands_1.txt`），EA轮询检测并执行，然后将结果写入对应的响应文件（如`AI_xxxxx.txt`）。
-   **实时数据流**: EA持续将账户信息、持仓订单、市场报价、新K线等数据写入`AI_Orders.txt`, `AI_Market_Data.txt`等文件，Python端实时监控这些文件以获取最新市场状态。

### 🗄️ 数据库增强与高级状态管理 (Database Enhancement & Advanced State Management)

-   **SQLite 数据库核心**: 项目使用 `src/services/order_db_manager.py` 管理一个本地SQLite数据库，它不仅是MT4订单的镜像，更是**增强的数据中心**。
-   **评论区状态管理**: 所有由AI开出的订单，其`Comment`都遵循 `L=0;G=A;S=PIN;M=N;ID=xxxx` 的严格格式。数据库会解析这个Comment，并将其作为结构化数据存储，用于高级的仓位管理。
    -   `L`: 利润阶梯（Ladder）等级。
    -   `G`: 交易评级（Grade）。
    -   `S`: 信号类型（Signal）。
    -   `M`: 管理状态（Management）。
    -   `ID`: 唯一交易ID。
-   **部分平仓与订单继承**: 当一个订单被部分平仓时，MT4会关闭原订单并生成一个新订单。本系统能智能捕捉这一行为，并在数据库中将新订单的`extends`字段指向原订单，同时**继承**原订单的所有AI元数据（如交易ID、评级等），确保了管理逻辑的连续性。
-   **数据预计算与缓存**: 数据库会为新订单**预先计算并存储**所有的利润阶梯（TP1-TP8）价格，极大加速了后续的管理决策过程。

### 🖥️ 直观的PyQt5图形化界面 (Intuitive PyQt5 GUI)

-   **一站式指挥中心**: 基于 **PyQt5** 和 **qasync**（实现PyQt与asyncio的无缝结合）构建，提供了一个流畅不卡顿的图形界面。
-   **参数化配置**: 在GUI中即可方便地选择AI模型、策略档案，并管理API密钥。
-   **实时数据展示**: 主界面清晰地展示了账户净值、持仓列表、AI状态以及详细的思考日志。
-   **内置图表工具**: 集成了 **pyqtgraph**，可以快速调出任一交易对的K线图进行预览。

## 📸 软件截图

<p align="center">
  <img src="./images/cover_software_main.png" alt="软件主界面" width="800"/>
  <br>
  <em>软件主界面：集成了AI代理配置、策略选择、账户状态和实时持仓，所有信息一目了然。</em>
</p>
<p align="center">
  <img src="./images/cover_software_log_01.png" alt="AI思考日志" width="800"/>
  <br>
  <em>AI思考日志：实时展示AI的完整决策链。</em>
</p>
<p align="center">
  <img src="./images/cover_software_log_02.png" alt="AI思考日志" width="800"/>
  <br>
  <em>AI思考日志：实时展示AI的完整决策链。</em>
</p>
<p align="center">
  <img src="./images/cover_software_chart.png" alt="K线图表查看器" width="800"/>
  <br>
  <em>内置的K线图表查看器：支持查看K线、指标和形态，双击持仓即可快速打开。</em>
</p>

## 🚀 快速开始

### 系统要求

1.  **操作系统**: Windows (因为 MetaTrader 4 主要是 Windows 平台)。
2.  **Python**: 3.8 或更高版本。
3.  **交易平台与API**:
    | 软件/工具           | 下载/安装说明                                                                                                                  | 备注                                                              |
    | :------------------ | :----------------------------------------------------------------------------------------------------------------------------- | :---------------------------------------------------------------- |
    | **MetaTrader 4**    | [官方网站](https://www.metatrader4.com/) 或您的经纪商网站                                                                      | **必须**。本程序的核心交易终端。                                   |
    | **LLM API Keys**    | [OpenAI](https://platform.openai.com/), [DeepSeek](https://platform.deepseek.com/), [Moonshot](https://platform.moonshot.cn/) | **至少需要一个**。用于驱动AI交易员。                              |
    | **Jina API Key**    | [Jina AI Cloud](https://cloud.jina.ai/)                                                                                        | *可选*。用于 `tool_news` 新闻搜索功能。                          |

### 安装与启动

本项目提供两种安装方式，请根据您的需求选择其一：

#### 方式一：小白版 (推荐) - 直接运行

这种方式最简单，无需安装 Python 环境，适合希望直接使用的用户。

1.  **下载预编译包**:
    -   访问本项目的 [**Releases 页面**](https://github.com/toki-plus/ai-trader-for-mt4/releases)。
    -   在最新版本中，下载名为 `AI-Trader-For-MT4.zip` 的文件。
    -   将 `AI-Trader-For-MT4.zip` 解压到您希望安装的任意位置（例如 `D:\AI-Trader`）。

2.  **配置 MT4 Expert Advisor (EA):**
    -   打开您的 MT4 终端，点击菜单栏 `文件(File)` -> `打开数据文件夹(Open Data Folder)`。
    -   在弹出的文件夹中，进入 `MQL4/Experts/` 目录。
    -   将您刚刚解压的文件夹中的 `MQL4/Experts/AI_Trader_for_MT4.mq4` 文件复制到这里。
    -   返回 MT4 终端，在左侧“导航器(Navigator)”窗口中，右键点击“EA交易(Expert Advisors)”并选择“刷新(Refresh)”。
    -   `AI_Trader_for_MT4` 现在应该会出现在列表中。**将其拖拽到任意一个图表上**。在弹出的配置窗口中，切换到“常用(Common)”标签，确保 **“允许DLL导入(Allow DLL imports)”** 和 **“允许实时自动交易(Allow live trading)”** 均已勾选。点击“确定”后，图表右上角应出现一个😊笑脸图标。

3.  **配置 API Keys 和 MT4 路径:**
    -   在您解压的程序文件夹中，找到 `.env.example` 文件，将其复制一份并重命名为 `.env`。
    -   打开 `.env` 文件，填入您的LLM API密钥和Jina API密钥。
    -   **[关键步骤]** 找到并修改 `MT4_DATA_PATH` 变量。此路径必须是您在第2步中打开的MT4数据文件夹下的 `MQL4/Files` 目录的**绝对路径**。
        ```text
        # 示例:
        MT4_DATA_PATH="C:/Users/YourUsername/AppData/Roaming/MetaQuotes/Terminal/YOUR_TERMINAL_ID/MQL4/Files"
        ```

4.  **运行程序：**
    -   双击解压文件夹中的 `AI-Trader-For-MT4.exe` 文件即可启动程序。

#### 方式二：开发者版 - 从源码运行

这种方式适合希望研究、修改或贡献代码的开发者。

1.  **克隆本仓库：**
    ```bash
    git clone https://github.com/toki-plus/ai-trader-for-mt4.git
    cd ai-trader-for-mt4
    ```

2.  **配置 MT4 Expert Advisor (EA):**
    -  (此步骤与“小白版”中的第2步完全相同，请参考上文)

3.  **创建并激活 Python 虚拟环境 (推荐)：**
    ```bash
    python -m venv venv
    # Windows 系统
    venv\Scripts\activate
    ```

4.  **安装依赖库：**
    ```bash
    pip install -r requirements.txt
    ```

5.  **配置 API Keys 和 MT4 路径:**
    -  (此步骤与“小白版”中的第3步完全相同，请参考上文)

6.  **运行程序：**
    ```bash
    python main.py
    ```

## 📖 使用指南

1.  **启动与连接**:
    -   确保您的 MT4 终端已运行，并且 `AI_Trader_for_MT4` EA 正在一个图表上活动（右上角有😊笑脸）。
    -   运行 `python main.py` 启动 Python 主程序。
    -   观察GUI左上角，`MT4 Connection Settings` 应显示为绿色“Connected”，代表与MT4通信成功。

2.  **配置AI人格与策略**:
    -   在 "AI Agent Configuration" 区域，从 **AI Model** 下拉菜单中选择一个“大脑”（如 `DeepSeek`）。
    -   在 **Strategy Profile** 下拉菜单中选择一个交易档案。这决定了AI的交易节奏（`15-Minute` 对应快节奏日内交易，`4-Hour` 对应慢节奏波段交易）。

3.  **启动自主交易**:
    -   点击 **"RUN"** 按钮。
    -   AI代理将进入激活状态，并开始按照其内部“交易法则”和SOP进行周期性的市场分析、仓位管理和交易决策。

4.  **观察与学习**:
    -   **"Logs" 区域**是您的主监视窗口。您可以在这里实时看到AI的完整思考过程，理解它为何做出或不做出某个决策。
    -   **"MT4 Open Positions" 区域**会实时同步您在MT4中的持仓情况。
    -   要停止AI，请点击 **"STOP"**。AI会在完成当前决策循环后安全、优雅地停止。

## ⚠️ 重要免责声明

本项目仅供技术学习和研究目的使用。自动化交易系统固有高风险，可能导致重大的财务损失。

> **强烈建议您仅在模拟账户（Demo Account）上运行此项目进行测试和验证。切勿在真实资金账户上使用。**

作者不对任何因使用此软件（或其任何部分）而直接或间接导致的财务损失或其他任何形式的损失负责。在真实账户上运行此软件的风险完全由您自行承担。

---

<p align="center">
  <strong>业务定制与技术交流，请添加：</strong>
</p>
<table align="center">
  <tr>
    <td align="center">
      <img src="./images/wechat.png" alt="微信二维码" width="200"/>
      <br />
      <sub><b>个人微信</b></sub>
      <br />
      <sub>微信号: toki-plus (请备注“GitHub定制”)</sub>
    </td>
    <td align="center">
      <img src="./images/gzh.png" alt="公众号二维码" width="200"/>
      <br />
      <sub><b>公众号</b></sub>
      <br />
      <sub>获取最新技术分享</sub>
    </td>
  </tr>
</table>

## 📂 我的其他开源项目

-   **[Netease Downloader](https://github.com/toki-plus/netease-downloader)**: 一款优雅、功能丰富的网易云音乐下载器，支持无损/高品质音质、歌单/专辑批量下载、扫码登录和自动写入ID3元数据。
-   **[Auto USPS Tracker](https://github.com/toki-plus/auto-usps-tracker)**: 专为跨境电商卖家设计的高效USPS批量物流追踪器，支持防屏蔽抓取并生成精美Excel报告。
-   **[AI Mixed Cut](https://github.com/toki-plus/ai-mixed-cut)**: 颠覆性AI内容生产工具，通过“解构-重构”模式将现有视频深度解析并全自动生成全新原创短视频。
-   **[AI Video Workflow](https://github.com/toki-plus/ai-video-workflow)**: 全自动AI原生视频生成工作流，集成文生图、图生视频和文生音乐模型，一键创作AIGC短视频。
-   **[AI Highlight Clip](https://github.com/toki-plus/ai-highlight-clip)**: AI驱动的智能剪辑工具，全自动从长视频分析、提取“高光时刻”，并生成爆款标题。
-   **[AI TTV Workflow](https://github.com/toki-plus/ai-ttv-workflow)**: AI驱动的文本转视频工具，自动将文案转化为带配音、字幕和封面的短视频，支持文案提取/二创/翻译。
-   **[AB Video Deduplicator](https://github.com/toki-plus/AB-Video-Deduplicator)**: 创新“高帧率抽帧混合”技术，重构视频数据指纹，规避短视频平台原创度检测/查重机制。
-   **[Video Mover](https://github.com/toki-plus/video-mover)**: 全自动化内容创作流水线，自动监听下载视频、多维度去重、AI生成标题，一键发布多平台。

## 🤝 参与贡献

欢迎任何形式的贡献！如果你有新的功能点子、发现了Bug，或者有任何改进建议，请：
-   提交一个 [Issue](https://github.com/toki-plus/ai-trader-for-mt4/issues) 进行讨论。
-   Fork 本仓库并提交 [Pull Request](https://github.com/toki-plus/ai-trader-for-mt4/pulls)。

如果这个项目对你有帮助，请不吝点亮一颗 ⭐！

## 📜 开源协议



本项目基于 MIT 协议开源。详情请见 [LICENSE](LICENSE) 文件。
