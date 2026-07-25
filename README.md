# 智投研 AI · 多智能体股票/基金分析平台

一个**多智能体（Multi-Agent）投研系统**，不是单个 AI 问答。六阶段流水线：

1. **数据中心**（5 路并行：技术面 / 基本面 / 新闻 / 资金流 / 市场情绪）
2. **AI 投研委员会**（技术派·价值派·趋势派·新闻派·资金派·风险派 六方多空辩论 → 研究主管裁决 BUY/SELL/HOLD）
3. **AI 交易计划**（分批建仓 / 止盈止损 / Kelly 仓位 / 风险收益比）
4. **AI 风险委员会**（风险等级 + 操作建议）
5. **AI 组合优化**（集中度 / 配置建议）
6. **AI 复盘中心**

> ⚠️ 所有结论均为 AI 基于公开数据的推断，仅供研究学习，不构成任何投资建议。请勿据此直接实盘交易。

---

## 技术栈

- 后端：FastAPI + DeepSeek（OpenAI 兼容接口）
- 前端：原生 HTML/JS + ECharts（金融终端风格，红涨绿跌）
- 数据源：**腾讯财经 + 东方财富 公开接口**（准实时，未授权商用；自动选择可达源，不可用时优雅降级）
- 部署：Docker（Render / Railway 免费套餐，或任意容器平台）

---

## 一、本地运行

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate      # 或你的虚拟环境
pip install -r requirements.txt

cp .env.example .env        # 然后编辑 .env，填入 DEEPSEEK_API_KEY
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

浏览器打开 http://127.0.0.1:8000

- `GET  /api/health`        健康检查（返回模型与数据源）
- `GET  /api/quote?query=贵州茅台`   仅拉真实数据（秒级，不调大模型）
- `POST /api/analyze`      完整六阶段分析
  ```json
  { "query": "贵州茅台", "fast": false }
  ```

---

## 二、部署上线（免费云平台）

### 方式 A：Render（推荐，免费，选 Singapore 区域离数据源更近）

1. 把本仓库推到你的 GitHub（见下方「初始化 Git 仓库」）。
2. 打开 https://dashboard.render.com → **New + → Blueprint** → 关联仓库。
3. Render 会自动读取 `render.yaml`：创建 Web 服务、用 Docker 构建、设健康检查 `/api/health`。
4. 在 Render 控制台 **Environment** 中设置环境变量 `DEEPSEEK_API_KEY`（你的真实 Key）。
5. 点击 Deploy。完成后获得 `https://ai-invest-platform.onrender.com`。

> 免费套餐特点：15 分钟无访问会休眠，首次唤醒约 30 秒；单次请求超时 60 秒，
> 若分析偏慢可在前端用「快速模式」。

### 方式 B：Railway

1. 推送仓库到 GitHub。
2. https://railway.app → **New Project → Deploy from GitHub repo**。
3. Railway 自动识别 `Dockerfile` 与 `railway.json`。
4. 在 Variables 中添加 `DEEPSEEK_API_KEY`。
5. Deploy，获得 `https://xxx.up.railway.app`。

---

## 三、初始化 Git 仓库（首次）

```bash
cd ai-invest-platform
git init
git add .
git commit -m "feat: 智投研 AI 多智能体分析平台（Docker 化部署）"
git branch -M main
git remote add origin https://github.com/<你的用户名>/ai-invest-platform.git
git push -u origin main
```

> `.env`（含 API Key）已被 `.gitignore` 忽略，**不会**被提交。云端 Key 请在平台环境变量中设置。

---

## 四、环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key（**必填**，云端在平台配置） | 无 |
| `DEEPSEEK_BASE_URL` | DeepSeek 兼容接口地址 | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | 模型名 | `deepseek-v4-flash` |
| `HOST` | 绑定地址 | `0.0.0.0` |
| `PORT` | 端口（平台自动注入） | `8000` |

---

## 五、数据源与已知局限

- **主数据源**：腾讯财经 `qt.gtimg.cn`（实时行情）、`web.ifzq.gtimg.cn`（K 线）、`smartbox.gtimg.cn`（搜索）。
- **补充源**：东方财富（新闻、资金流），不可用时自动降级并提示。
- **更新频率**：行情为准实时（盘中最短分钟级延迟），非逐笔成交。
- **局限性**：
  - 数据为**公开接口聚合**，未经交易所/数据商商用授权，仅限研究学习；
  - 境外云（Render/Railway）访问国内数据源可能因地理距离变慢或被限流，建议选 Singapore 区域；
  - 资金流 / 部分衍生指标在受限网络下可能缺失，委员会会基于「数据有限」合理推断。
- **合规**：自用小圈子使用可保留完整 BUY/SELL 结论；若公开发布，请遵守当地证券咨询相关法规，显著标注「非投资建议」。

---

## 六、目录结构

```
ai-invest-platform/
├── Dockerfile            # 部署镜像
├── render.yaml           # Render Blueprint 配置
├── railway.json          # Railway 配置
├── .dockerignore
├── backend/
│   ├── main.py           # FastAPI 入口（同时托管前端静态文件）
│   ├── data_center.py    # Stage1 真实数据（腾讯+东方财富，5 路并行）
│   ├── ai_committee.py   # Stage2-5 DeepSeek 多智能体委员会
│   ├── requirements.txt
│   ├── .env.example
│   └── .env              # 本地用，已被 gitignore（勿提交）
└── frontend/
    └── index.html        # 金融终端风格前端，调用同域 /api
```
