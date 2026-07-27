"""
AI 投研委员会 (Stage 2-5)
================================
用 DeepSeek 基于真实数据包，生成：
- 6 派多空辩论 + 研究主管裁决 (BUY/SELL/HOLD) + 信心度
- 交易计划（分批建仓 / 止盈止损 / Kelly 仓位 / 风险收益比）
- 风险等级 + 操作建议
- 组合优化提示

所有结论均为 AI 推断，与客观数据分离展示。
"""
import json
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
_DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
_DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=_DEEPSEEK_API_KEY, base_url=_DEEPSEEK_BASE_URL)
    return _client

SYSTEM = """你是一个专业投研机构的多智能体协调系统。基于给定的【真实客观数据包】，
模拟 6 位分析师进行多空辩论，再由研究主管裁决，并生成交易计划与风险评估。

要求：
1. 严格基于提供的数据，不得编造数据中不存在的具体数值；数据缺失(N/A)时基于常识合理推断并说明"数据有限"。
2. 6 派角色：技术派、价值派、趋势派、新闻派、资金派、风险派。每人一句话观点(≤40字)，并给出 stance: buy/sell/hold。
3. 研究主管必须给出明确 action: BUY / SELL / HOLD，不能模糊；confidence 为 0-100 整数。
4. 交易计划要具体：三批建仓百分比、Kelly 建议仓位(占账户%)、止盈价、止损价、风险收益比。
5. 风险：risk_level 1-5(整数星级)，advice 取值 加仓/持有/减仓/清仓/等待 之一。
6. 全部用简体中文。只输出 JSON，不要多余文字。

输出 JSON 结构：
{
 "debate":[{"role":"技术派","stance":"buy","text":"..."}, ...6条],
 "verdict":{"action":"BUY","confidence":76,"summary":"研究主管总结(≤80字)"},
 "trade_plan":{"batches":[30,20,50],"kelly_pct":18,"take_profit":"¥2050","stop_loss":"¥1712","rr_ratio":"1:2.1","note":"..."},
 "risk":{"risk_level":4,"advice":"持有","reasons":["...","..."]},
 "portfolio_tip":"针对组合集中度/配置的一句建议"
}"""


def run_committee(data_pack: dict, name: str, fast: bool = False):
    user = f"标的：{name}\n真实数据包(来自腾讯财经/东方财富 公开数据)：\n{json.dumps(data_pack, ensure_ascii=False)}"
    if fast:
        user += "\n（快速模式：仅需 debate 和 verdict，其余可简略）"
    try:
        resp = _get_client().chat.completions.create(
            model=_DEEPSEEK_MODEL,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0.7,
            max_tokens=1400,
        )
        content = resp.choices[0].message.content
        data = json.loads(content)
        data["ok"] = True
        data["model"] = _DEEPSEEK_MODEL
        return data
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    demo = {"trend": "多头", "price": 1822, "macd": "金叉", "rsi": 62,
            "pe": 32, "roe": "28%", "main_fund": "净流入", "mood": "活跃"}
    print(json.dumps(run_committee(demo, "贵州茅台"), ensure_ascii=False, indent=2))


FUND_SYSTEM = """你是一个基金投研分析系统。给定某只公募基金【前十大重仓股数据包】
(来自东方财富 fundf10 公开数据，含重仓股名称、代码、占净值比例、所属行业、PE、PB，
以及组合层面的前3/前10集中度、HHI、行业分布、平均估值)，请基于这些数据生成分析。

要求：
1. 严格基于提供的数据，不得编造数据中不存在的具体数值；数据缺失(N/A)时基于常识合理推断并说明"数据有限"。
2. 6 派角色：技术派、价值派、行业派、趋势派、资金派、风险派。每人一句话观点(≤40字)，并给出 stance: buy/sell/hold。
3. 研究主管必须给出明确 action: BUY / SELL / HOLD（对"是否值得定投/继续持有该基金"的判断），confidence 为 0-100 整数。
4. 交易计划要具体：三只分批建仓百分比、Kelly 建议仓位(占账户%)、止盈思路、止损思路、风险收益比。
5. 风险：risk_level 1-5(整数星级)，advice 取值 加仓/持有/减仓/清仓/等待 之一，并给出 reasons。
6. 全部用简体中文。只输出 JSON，不要多余文字。

输出 JSON 结构：
{
 "debate":[{"role":"技术派","stance":"buy","text":"..."}, ...6条],
 "verdict":{"action":"HOLD","confidence":62,"summary":"研究主管总结(≤80字)"},
 "trade_plan":{"batches":[30,20,50],"kelly_pct":15,"take_profit":"净值+12%","stop_loss":"净值-8%","rr_ratio":"1:1.5","note":"..."},
 "risk":{"risk_level":3,"advice":"持有","reasons":["...","..."]},
 "portfolio_tip":"针对组合配置的一句建议"
}"""


def run_fund_committee(fund_pack: dict, name: str, fast: bool = False):
    user = (f"基金：{name}\n前十大重仓股数据包(来自东方财富 fundf10 公开数据)：\n"
            + json.dumps(fund_pack, ensure_ascii=False))
    if fast:
        user += "\n（快速模式：仅需 debate 和 verdict，其余可简略）"
    try:
        resp = _get_client().chat.completions.create(
            model=_DEEPSEEK_MODEL,
            messages=[{"role": "system", "content": FUND_SYSTEM},
                      {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0.7,
            max_tokens=1400,
        )
        content = resp.choices[0].message.content
        data = json.loads(content)
        data["ok"] = True
        data["model"] = _DEEPSEEK_MODEL
        return data
    except Exception as e:
        return {"ok": False, "error": str(e)}


PORTFOLIO_SYSTEM = """你是一个组合层面的 AI 投研顾问。给定一位投资者的【持仓组合诊断数据包】
(由系统基于其「我的组合」真实持仓计算，含总市值、累计收益、行业/类型分布、单一与 Top3 集中度、HHI、
最佳/最差持仓、风险等级与初步预警)，请基于这些数据给出组合层面的诊断与再平衡建议。

要求：
1. 严格基于提供的数据，不得编造数据中不存在的具体数值；数据缺失时基于常识合理推断并说明"数据有限"。
2. summary：2-3 句话的组合整体诊断（≤120字），口语化、有结论。
3. rebalance：3-4 条具体再平衡动作，每条含 action(减配/增配/持有/观望)、target(资产或行业名)、detail(一句话理由)。
4. risk_level：1-5 整数星级（与给定 risk_level 基本一致，可微调并说明）。
5. verdict：对组合整体的操作建议，取值 REBALANCE(需再平衡)/HOLD(维持)/ACCUMULATE(可加仓) 之一。
6. 全部用简体中文。只输出 JSON，不要多余文字。

输出 JSON 结构：
{
 "summary":"...",
 "rebalance":[{"action":"减配","target":"贵州茅台","detail":"单一占比偏高，建议降至25%以下"}, ...],
 "risk_level":4,
 "verdict":"REBALANCE",
 "portfolio_tip":"一句话配置建议"
}"""


def _portfolio_fallback(diag):
    """DeepSeek 不可用时的确定性回退，保证前端总有内容。"""
    rb = []
    for w in (diag.get("warnings") or [])[:3]:
        rb.append({"action": ("减配" if ("过高" in w or "显著" in w) else "观望"),
                   "target": "相关持仓", "detail": w})
    return {
        "summary": (f"组合共 {diag.get('holdings_count')} 只持仓，累计收益 "
                    f"{diag.get('total_pnl_pct')}%，最大单一持仓 {diag.get('top1', {}).get('name')} "
                    f"占比 {diag.get('top1', {}).get('weight')}%，风险等级 {diag.get('risk_level')}/5。"),
        "rebalance": rb or [{"action": "持有", "target": "全部",
                             "detail": "组合分散度良好，维持现状。"}],
        "risk_level": diag.get("risk_level", 3),
        "verdict": "REBALANCE" if diag.get("risk_level", 3) >= 4 else "HOLD",
        "portfolio_tip": (diag.get("warnings") or ["组合分散度良好。"])[0],
    }


def run_portfolio_committee(diag: dict, fast: bool = False):
    fb = _portfolio_fallback(diag)
    try:
        user = "持仓组合诊断数据包：\n" + json.dumps(diag, ensure_ascii=False)
        if fast:
            user += "\n（快速模式：仅需 summary 与 rebalance，其余可简略）"
        resp = _get_client().chat.completions.create(
            model=_DEEPSEEK_MODEL,
            messages=[{"role": "system", "content": PORTFOLIO_SYSTEM},
                      {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0.7,
            max_tokens=1200,
        )
        content = resp.choices[0].message.content
        data = json.loads(content)
        data["ok"] = True
        data["model"] = _DEEPSEEK_MODEL
        return data
    except Exception as e:
        fb["ok"] = False
        fb["error"] = str(e)
        return fb
