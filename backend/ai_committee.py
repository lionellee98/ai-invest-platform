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

_client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
)
_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

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
        resp = _client.chat.completions.create(
            model=_MODEL,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0.7,
            max_tokens=1400,
        )
        content = resp.choices[0].message.content
        data = json.loads(content)
        data["ok"] = True
        data["model"] = _MODEL
        return data
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    demo = {"trend": "多头", "price": 1822, "macd": "金叉", "rsi": 62,
            "pe": 32, "roe": "28%", "main_fund": "净流入", "mood": "活跃"}
    print(json.dumps(run_committee(demo, "贵州茅台"), ensure_ascii=False, indent=2))
