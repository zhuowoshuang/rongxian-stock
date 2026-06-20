# 融衔 (RongXian) — A 股 + 港股智能选股与信号系统

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python)
![Next.js](https://img.shields.io/badge/Next.js-14-black?logo=next.js)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green?logo=fastapi)
![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-blue?logo=typescript)
![License](https://img.shields.io/badge/License-MIT-yellow)

> **免责声明**：本系统仅用于研究和辅助分析，不构成任何投资建议。投资有风险，入市需谨慎。

## 功能特性

- **多维评分体系** — 质量(30) + 估值(20) + 成长(20) + 趋势(20) + 风险(10) = 100 分
- **智能信号生成** — BUY / ADD / WATCH / REDUCE / SELL 五级信号
- **实时市场数据** — 东方财富 + 腾讯 + 新浪多源数据，自动 fallback
- **5000+ 股票覆盖** — A 股 + 港股，99%+ 数据完整度
- **5 种回测策略** — 基本面 / 价值 / 成长 / 动量 / 质量优先
- **组合管理** — 信号驱动的自动建仓/加仓/减仓/清仓
- **技术指标** — MA / MACD / RSI / 布林带，标准算法
- **行业差异化评分** — 银行/保险等金融股使用不同负债率标准
- **中英文界面** — 完整的 i18n 支持
- **暗色/亮色主题** — 一键切换

## 一键部署

**点击下方按钮，直接从 GitHub 部署到线上：**

### 方案一：Vercel（前端，免费）

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/zhuowoshuang/rongxian-stock&root-directory=frontend&env=BACKEND_URL&envDescription=后端API地址&envLink=https://github.com/zhuowoshuang/rongxian-stock)

> 点击按钮 → 登录 Vercel → 自动部署前端 → 拿到 URL

**注意：** 前端需要后端配合。后端请用下方 Railway 按钮部署，然后把后端 URL 填入 `BACKEND_URL` 环境变量。

### 方案二：Railway（全栈，免费额度）

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template/zhuowoshuang/rongxian-stock?referralCode=mimo)

> 点击按钮 → 登录 Railway → 自动部署前后端 → 拿到 URL 直接访问

### 方案三：Render（全栈，免费）

1. Fork 本仓库
2. 访问 [render.com](https://render.com) → **New Web Service**
3. 连接你的 fork → 自动检测 `render.yaml` → 部署

### 方案四：Docker 一键运行

```bash
docker run -p 8000:8000 -p 3000:3000 zhuowoshuang/rongxian-stock
```

## 快速开始

### 方式一：Docker Compose（推荐）

```bash
# 1. 克隆项目
git clone https://github.com/YOUR_USERNAME/rongxian.git
cd rongxian

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的配置

# 3. 一键启动
docker-compose up --build

# 4. 访问
# 前端: http://localhost:3000
# 后端 API: http://localhost:8000/docs
# 默认账号: admin / admin123
```

### 方式二：本地开发

```bash
# 后端
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m app.seed        # 初始化数据
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
npm install
npm run dev
```

### 方式三：真实数据模式

```bash
# 设置环境变量使用真实数据源
export MOCK_DATA=false

# 拉取全量数据（约 15-30 分钟）
cd backend
python full_sync.py

# 启动服务
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 系统架构

```
┌─────────────────────────────────────────────────────┐
│                    Frontend (Next.js)                │
│  Dashboard │ Stocks │ Signals │ Pools │ Backtest     │
└────────────────────────┬────────────────────────────┘
                         │ API Proxy
┌────────────────────────┴────────────────────────────┐
│                  Backend (FastAPI)                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │ Auth     │ │ Dashboard│ │ Backtest │            │
│  └──────────┘ └──────────┘ └──────────┘            │
│  ┌──────────────────────────────────────┐          │
│  │         Services Layer               │          │
│  │  Scoring │ Signal │ Report │ Portfolio│          │
│  └──────────────────────────────────────┘          │
│  ┌──────────────────────────────────────┐          │
│  │       Data Providers                 │          │
│  │  EastMoney │ Tencent │ Sina │ Yahoo  │          │
│  └──────────────────────────────────────┘          │
└────────────────────────┬────────────────────────────┘
                         │
              ┌──────────┴──────────┐
              │   SQLite / PostgreSQL │
              └─────────────────────┘
```

## 评分模型

| 维度 | 满分 | 评估指标 |
|------|------|----------|
| 质量 | 30 | ROE、经营现金流、毛利率、资产负债率 |
| 估值 | 20 | PE、PB、PEG、股息率 |
| 成长 | 20 | 营收增长、利润增长、CAGR |
| 趋势 | 20 | MA60 方向、MACD、RSI、成交量 |
| 风险 | 10 | 最大回撤、业绩稳定性、负债/现金流 |

### 评级规则

| 分数 | 评级 | 含义 |
|------|------|------|
| ≥ 85 | BUY | 买入 |
| 75-84 | ADD | 加仓 |
| 65-74 | WATCH | 观察 |
| 50-64 | REDUCE | 减仓 |
| < 50 | SELL | 卖出 |

## 回测策略

| 策略 | 选股条件 |
|------|----------|
| 基本面中长期 | 总分 ≥ 65 |
| 价值投资 | 估值 ≥ 15 且 质量 ≥ 20 |
| 成长投资 | 成长 ≥ 15 且 总分 ≥ 60 |
| 趋势动量 | 趋势 ≥ 15 且 总分 ≥ 60 |
| 质量优先 | 质量 ≥ 24 且 风险 ≥ 7 |

## API 文档

启动后端后访问：http://localhost:8000/docs

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 登录 |
| GET | `/api/dashboard` | 仪表盘 |
| GET | `/api/stocks/{symbol}` | 股票详情 |
| GET | `/api/signals` | 信号列表 |
| GET | `/api/pools?type=` | 股票池 |
| POST | `/api/backtest/run` | 运行回测 |
| GET | `/api/reports` | 报告列表 |

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | 数据库连接 | `sqlite:///./stock_agent.db` |
| `JWT_SECRET_KEY` | JWT 密钥 | 自动生成 |
| `MOCK_DATA` | 使用 Mock 数据 | `true` |
| `LLM_API_URL` | LLM API 地址 | - |
| `LLM_API_KEY` | LLM API 密钥 | - |

## 技术栈

| 层 | 技术 |
|----|------|
| 前端 | Next.js 14 + TypeScript + Tailwind CSS + Recharts |
| 后端 | FastAPI + SQLAlchemy + APScheduler |
| 数据 | 东方财富 + 腾讯 + 新浪 + Yahoo Finance |
| 部署 | Docker Compose + SQLite/PostgreSQL |

## 项目结构

```
├── backend/
│   ├── app/
│   │   ├── api/              # API 路由
│   │   ├── models/           # 数据库模型
│   │   ├── services/         # 业务逻辑
│   │   ├── data_providers/   # 数据源适配器
│   │   ├── core/             # 配置
│   │   └── main.py           # 入口
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── app/              # 页面
│   │   ├── components/       # 组件
│   │   ├── lib/              # 工具
│   │   └── types/            # 类型
│   ├── Dockerfile
│   └── package.json
├── docker-compose.yml
└── .env.example
```

## 贡献

欢迎提交 Issue 和 Pull Request！

## License

MIT
