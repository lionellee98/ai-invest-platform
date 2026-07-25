"""
数据采集中心 (Stage 1)
================================
真实数据来源（免费、公开、无需 key）：
  · 行情 / K线 / 估值 / 换手：腾讯财经  qt.gtimg.cn / web.ifzq.gtimg.cn
  · 标的搜索：腾讯 smartbox（GBK）+ 东方财富 suggest（兜底）
  · 新闻资讯：东方财富 search-api（准实时）
  · 资金流向：东方财富 push2his（如被限流则优雅降级）

更新频率：行情准实时（交易时段分钟级）；资金流按交易日；新闻准实时。
已知局限：均为交易所/门户公开接口，非官方授权文档，字段可能随页面调整；
          场外基金(OTC)无实时行情，仅股票/ETF/指数可完整分析；仅供研究，非商用。

传输层：requests 优先，若被 TLS 指纹/代理拦截，自动回退系统 curl（本地与云端均可用）。
"""
import datetime as _dt
import json
import re
import subprocess
import urllib.parse

try:
    import requests
except Exception:
    requests = None

SOURCE_TAG = "腾讯财经 + 东方财富 公开接口（准实时，仅供研究，非商用授权）"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


# ------------------------------------------------------------ 传输层
# 不同数据源对 Referer 要求不同：腾讯财经用 gu.qq.com，东方财富基金接口需对应域名
_TENCENT_REF = "https://gu.qq.com/"
_EM_REF = "https://fundf10.eastmoney.com/"
_EM_SEARCH_REF = "https://fundsuggest.eastmoney.com/"


def http_bytes(url: str, timeout: int = 15, referer: str = _TENCENT_REF) -> bytes:
    headers = {"User-Agent": _UA, "Referer": referer,
               "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9"}
    if requests is not None:
        try:
            r = requests.get(url, timeout=timeout, headers=headers)
            if r.status_code == 200 and r.content:
                return r.content
        except Exception:
            pass
    try:
        o = subprocess.run(
            ["curl", "-s", "-m", str(timeout),
             "-H", f"User-Agent: {_UA}",
             "-H", f"Referer: {referer}",
             "-H", "Accept: */*", url],
            capture_output=True, timeout=timeout + 5)
        return o.stdout or b""
    except Exception:
        return b""


def http_text(url: str, encoding: str = "utf-8", timeout: int = 15,
              referer: str = _TENCENT_REF) -> str:
    b = http_bytes(url, timeout, referer=referer)
    if not b:
        return ""
    try:
        return b.decode(encoding, errors="replace")
    except Exception:
        return b.decode("utf-8", errors="replace")


def http_json(url: str, timeout: int = 15, referer: str = _TENCENT_REF):
    txt = http_text(url, "utf-8", timeout, referer=referer)
    if not txt:
        return None
    try:
        return json.loads(txt)
    except Exception:
        s, e = txt.find("("), txt.rfind(")")
        if 0 <= s < e:
            try:
                return json.loads(txt[s + 1:e])
            except Exception:
                return None
    return None


# ------------------------------------------------------------ 标的解析
def resolve_symbol(query: str):
    """→ {code,name,tx,market,type}. tx 形如 'sh600519' 供腾讯接口用。"""
    q = (query or "").strip()
    if not q:
        return None
    # 1) 腾讯 smartbox（GBK）
    txt = http_text("https://smartbox.gtimg.cn/s3/?t=all&q=" + urllib.parse.quote(q), "gbk")
    m = re.search(r'v_hint="([^"]*)"', txt or "")
    if m and m.group(1):
        first = m.group(1).split("^")[0]
        parts = first.split("~")
        if len(parts) >= 4:
            mk, code, name = parts[0], parts[1], parts[2]
            # \uXXXX 解码
            try:
                name = name.encode().decode("unicode_escape").encode("latin1").decode("utf-8")
            except Exception:
                pass
            if name.startswith("\\u"):
                try:
                    name = bytes(name, "utf-8").decode("unicode_escape")
                except Exception:
                    pass
            typ = parts[4] if len(parts) > 4 else ""
            if mk in ("sh", "sz", "bj"):
                return {"code": code, "name": _u(name), "tx": mk + code,
                        "market": mk, "type": typ}
    # 2) 东财 suggest 兜底
    d = http_json("https://searchapi.eastmoney.com/api/suggest/get?type=14"
                  "&token=D43BF722C8E33BDC906FB84D85E326E8&count=8&input=" + urllib.parse.quote(q))
    try:
        r = d["QuotationCodeTable"]["Data"][0]
        secid = r["QuoteID"]  # '1.600519'
        mk = "sh" if secid.startswith("1.") else "sz"
        return {"code": r["Code"], "name": r["Name"], "tx": mk + r["Code"],
                "market": mk, "type": r.get("Classify", "")}
    except Exception:
        pass
    # 3) 纯数字猜测
    if q.isdigit():
        mk = "sh" if q.startswith("6") else "sz"
        return {"code": q, "name": q, "tx": mk + q, "market": mk, "type": ""}
    return None


def _u(s):
    if isinstance(s, str) and "\\u" in s:
        try:
            return s.encode("latin1", "ignore").decode("unicode_escape")
        except Exception:
            return s
    return s


# ------------------------------------------------------------ 腾讯实时行情
def _quote(tx: str):
    txt = http_text("https://qt.gtimg.cn/q=" + tx, "gbk")
    m = re.search(r'="([^"]*)"', txt or "")
    if not m:
        return None
    f = m.group(1).split("~")
    def num(i):
        try:
            return float(f[i])
        except Exception:
            return None
    if len(f) < 46:
        return None
    return {
        "price": num(3), "prev": num(4), "open": num(5),
        "change": num(31), "change_pct": num(32),
        "high": num(33), "low": num(34),
        "amount_wan": num(37), "turnover": num(38), "pe": num(39),
        "circ_mktcap_yi": num(44), "mktcap_yi": num(45), "pb": num(46),
    }


# ------------------------------------------------------------ Agent 1 技术面（腾讯K线）
def agent_technical(tx: str):
    out = {"ok": False, "source": "腾讯财经 日K(前复权)"}
    d = http_json(f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tx},day,,,120,qfq")
    try:
        node = d["data"][tx]
        arr = node.get("qfqday") or node.get("day")
        rows = [[r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4])] for r in arr]
        # [date, open, close, high, low]
        closes = [r[2] for r in rows]
        if len(closes) < 30:
            return out
        def ma(n): return round(sum(closes[-n:]) / n, 2)
        ma5, ma20, ma60 = ma(5), ma(20), ma(min(60, len(closes)))
        gains = [max(closes[i] - closes[i - 1], 0) for i in range(-14, 0)]
        losses = [max(closes[i - 1] - closes[i], 0) for i in range(-14, 0)]
        ag, al = sum(gains) / 14, sum(losses) / 14
        rsi = round(100 - 100 / (1 + ag / al), 1) if al else 100.0
        def ema(data, n):
            k = 2 / (n + 1); e = data[0]
            for p in data[1:]:
                e = p * k + e * (1 - k)
            return e
        dif = ema(closes, 12) - ema(closes, 26)
        difs = [ema(closes[:i + 1], 12) - ema(closes[:i + 1], 26) for i in range(len(closes))]
        dea = ema(difs[-20:], 9)
        macd = "金叉" if dif > dea else "死叉"
        last = closes[-1]
        trend = "多头" if last > ma20 > ma60 else ("空头" if last < ma20 < ma60 else "震荡")
        out.update({"ok": True, "price": round(last, 2), "ma5": ma5, "ma20": ma20, "ma60": ma60,
                    "rsi": rsi, "macd": macd, "dif": round(dif, 3), "dea": round(dea, 3),
                    "trend": trend, "kline": rows[-40:]})
    except Exception as e:
        out["err"] = str(e)
    return out


# ------------------------------------------------------------ Agent 2 基本面
def agent_fundamental(quote: dict):
    out = {"ok": False, "source": "腾讯财经 实时估值"}
    if quote and quote.get("pe") is not None:
        out.update({"ok": True, "pe": quote.get("pe"), "pb": quote.get("pb"),
                    "mktcap": (f"{quote['mktcap_yi']:.0f}亿" if quote.get("mktcap_yi") else None)})
    return out


# ------------------------------------------------------------ Agent 3 新闻
def agent_news(name: str):
    out = {"ok": False, "source": "东方财富 资讯搜索", "items": []}
    param = {"uid": "", "keyword": name, "type": ["cmsArticleWebOld"],
             "client": "web", "clientType": "web",
             "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "time",
                                            "pageIndex": 1, "pageSize": 6}}}
    url = ("https://search-api-web.eastmoney.com/search/jsonp?cb=x&param="
           + urllib.parse.quote(json.dumps(param, ensure_ascii=False)))
    d = http_json(url)
    try:
        for a in d["result"]["cmsArticleWebOld"][:6]:
            t = re.sub(r"</?em>", "", a.get("title", ""))
            out["items"].append({"title": t, "time": a.get("date", "")})
        out["ok"] = len(out["items"]) > 0
    except Exception:
        pass
    return out


# ------------------------------------------------------------ Agent 4 资金面
def agent_fund_flow(secid_em: str):
    out = {"ok": False, "source": "东方财富 资金流"}
    url = (f"https://push2his.eastmoney.com/api/qt/stock/fflow/kline/get?secid={secid_em}"
           "&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56"
           "&klt=101&lmt=6&ut=b2884a393a59ad64002292a3e90d46a5")
    d = http_json(url, timeout=10)
    try:
        klines = d["data"]["klines"]
        recent = [float(k.split(",")[1]) for k in klines]
        main_net = recent[-1]
        streak = 0
        for x in reversed(recent):
            if (x > 0) == (main_net > 0):
                streak += 1
            else:
                break
        out.update({"ok": True, "date": klines[-1].split(",")[0], "main_net": _fmt_money(main_net),
                    "main_state": "净流入" if main_net > 0 else "净流出",
                    "streak": f"连续{streak}日{'流入' if main_net>0 else '流出'}"})
    except Exception:
        out["note"] = "资金流接口暂不可用（沙箱网络限流），云端部署可正常获取"
    return out


# ------------------------------------------------------------ Agent 5 情绪
def agent_sentiment(quote: dict):
    out = {"ok": False, "source": "换手率/涨跌推断"}
    if quote and quote.get("turnover") is not None:
        turn = quote["turnover"]
        out.update({"ok": True, "turnover": turn, "change_pct": quote.get("change_pct"),
                    "mood": "活跃" if turn > 3 else ("温和" if turn > 1 else "清淡")})
    return out


# ------------------------------------------------------------ 汇总
def collect_all(query: str):
    sym = resolve_symbol(query)
    if not sym:
        return {"ok": False, "error": f"未找到标的：{query}"}
    tx, name = sym["tx"], sym["name"]
    secid_em = ("1." if sym["market"] == "sh" else "0.") + sym["code"]

    quote = _quote(tx)
    tech = agent_technical(tx)
    fund = agent_fundamental(quote)
    news = agent_news(name)
    flow = agent_fund_flow(secid_em)
    emo = agent_sentiment(quote)

    pack = {
        "name": name, "code": sym["code"],
        "price": tech.get("price") or (quote or {}).get("price"),
        "change_pct": (quote or {}).get("change_pct"),
        "trend": tech.get("trend", "N/A"), "macd": tech.get("macd", "N/A"),
        "rsi": tech.get("rsi"), "pe": fund.get("pe"), "pb": fund.get("pb"),
        "main_fund": flow.get("main_state", "N/A"), "fund_streak": flow.get("streak"),
        "news_count": len(news.get("items", [])), "mood": emo.get("mood", "N/A"),
    }
    return {
        "ok": True, "symbol": sym, "source": SOURCE_TAG,
        "updated_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "agents": {"technical": tech, "fundamental": fund,
                   "news": news, "fund_flow": flow, "sentiment": emo},
        "data_pack": pack,
    }


# ------------------------------------------------------------ 基金（降级分析）
def _em_secid(code: str) -> str:
    """东方财富 secid：沪市 1. 深市 0. 前缀。"""
    return ("1." if str(code).startswith("6") else "0.") + str(code)


def resolve_fund(query: str):
    """东方财富基金搜索，返回 {code,name,type}。找不到返回 None。"""
    q = (query or "").strip()
    if not q:
        return None
    # 1) 东方财富基金搜索（需对应 Referer）
    url = ("https://fundsuggest.eastmoney.com/FundSearch/api/FundSearch/GSGQSearch?keyword="
           + urllib.parse.quote(q))
    d = http_json(url, timeout=10, referer=_EM_SEARCH_REF)
    try:
        res = d["data"]["fundSearchResult"]["results"]
        if res:
            r = res[0]
            return {"code": r["code"], "name": r["name"], "type": r.get("type", "")}
    except Exception:
        pass
    # 2) 备选搜索域名
    url2 = ("https://fundapi.eastmoney.com/fundSearch/api/FundSearch/GSGQSearch?keyword="
            + urllib.parse.quote(q))
    d2 = http_json(url2, timeout=10, referer=_EM_SEARCH_REF)
    try:
        res = d2["data"]["fundSearchResult"]["results"]
        if res:
            r = res[0]
            return {"code": r["code"], "name": r["name"], "type": r.get("type", "")}
    except Exception:
        pass
    # 3) 纯 6 位数字：用天天基金净值接口反查名称（极稳，无需特殊 Referer）
    if q.isdigit() and len(q) == 6:
        nm = _fund_name_by_code(q)
        return {"code": q, "name": nm or q, "type": ""}
    return None


def _fund_name_by_code(code: str):
    """天天基金(gz.1234567)净值接口反查基金名称，纯 6 位代码可用。"""
    txt = http_text(f"https://fundgz.1234567.com.cn/js/{code}.js",
                    "utf-8", timeout=10)
    if not txt:
        return None
    m = re.search(r'name["\s]*:"([^"]+)"', txt)
    return m.group(1) if m else None


def get_fund_holdings(code: str):
    """东方财富 fundf10 前十大重仓股（需 fundf10 Referer）。返回 {ok,date,holdings}。"""
    out = {"ok": False, "holdings": [], "date": ""}
    url = (f"https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc"
           f"&code={code}&topline=10")
    txt = http_text(url, "utf-8", timeout=12, referer=_EM_REF)
    if not txt:
        return out
    m = re.search(r'content:"(.*?)"\s*,\s*arryear', txt, re.S) or re.search(r'content:"(.*?)"', txt, re.S)
    if not m:
        return out
    content = m.group(1).replace('\\"', '"').replace("\\/", "/")
    rows = re.findall(r"<tr>(.*?)</tr>", content, re.S)
    holdings = []
    for row in rows:
        if "股票代码" in row or "序号" in row or "股票名称" in row:
            continue
        code_m = re.search(r">(\d{6})</a>", row)
        if not code_m:
            continue
        code = code_m.group(1)
        name = None
        for a in re.findall(r">([^<]+)</a>", row):
            a = a.strip()
            if re.fullmatch(r"\d{6}", a):
                continue
            if a and not a.isdigit():
                name = a
                break
        pct_m = re.search(r"([\d.]+)%", row)
        if code and name and pct_m:
            holdings.append({"code": code, "name": name, "pct": float(pct_m.group(1))})
    if holdings:
        out["ok"] = True
        out["holdings"] = holdings[:10]
        dm = re.search(r"curyear[:\s]*\"?(\d{4})", txt)
        if dm:
            out["date"] = dm.group(1)
    return out


def get_stock_industry(secid_em: str):
    """东方财富个股行业（f127）。"""
    d = http_json(
        f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid_em}&fields=f57,f58,f127",
        timeout=8, referer=_EM_REF)
    try:
        return d["data"].get("f127") or ""
    except Exception:
        return ""


def collect_fund_analysis(query: str):
    """
    基金降级分析：解析基金 → 取前十大重仓股 → 逐个补充行业/估值 → 计算集中度与行业分布。
    返回 {ok, name, code, date, holdings, metrics, fund_pack, source, updated_at}。
    """
    fnd = resolve_fund(query)
    if not fnd:
        return {"ok": False, "error": "未找到对应基金（请确认代码或名称是否正确）"}
    code, name = fnd["code"], fnd["name"]
    h = get_fund_holdings(code)
    if not h.get("ok") or not h["holdings"]:
        return {"ok": False,
                "error": "该基金前十大重仓股数据暂不可用（公开数据源限流），请稍后重试",
                "source_note": "东方财富 fundf10 接口"}
    holdings = h["holdings"]
    for it in holdings:
        try:
            sec = _em_secid(it["code"])
            q = _quote(("sh" if it["code"].startswith("6") else "sz") + it["code"])
            it["pe"] = (q or {}).get("pe")
            it["pb"] = (q or {}).get("pb")
            it["industry"] = get_stock_industry(sec) or "—"
        except Exception:
            it.setdefault("pe", None)
            it.setdefault("pb", None)
            it.setdefault("industry", "—")

    # 行业分布（按占净值加权）
    ind_map = {}
    for it in holdings:
        ind_map[it.get("industry", "—")] = ind_map.get(it.get("industry", "—"), 0) + it["pct"]
    ind_dist = [{"name": k, "pct": round(v, 2)}
                for k, v in sorted(ind_map.items(), key=lambda x: -x[1])]

    top3 = round(sum(it["pct"] for it in holdings[:3]), 2)
    top10 = round(min(sum(it["pct"] for it in holdings), 100), 2)
    hhi = round(sum((it["pct"] / 100) ** 2 for it in holdings), 4)
    pes = [it["pe"] for it in holdings if it.get("pe") is not None]
    pbs = [it["pb"] for it in holdings if it.get("pb") is not None]
    avg_pe = round(sum(pes) / len(pes), 1) if pes else None
    avg_pb = round(sum(pbs) / len(pbs), 2) if pbs else None
    concentration = "高" if top3 >= 40 else ("中" if top3 >= 25 else "低")

    metrics = {
        "count": len(holdings), "top3_pct": top3, "top10_pct": top10, "hhi": hhi,
        "industry_dist": ind_dist, "avg_pe": avg_pe, "avg_pb": avg_pb,
        "concentration": concentration,
    }
    fund_pack = {
        "name": name, "code": code, "holdings_count": len(holdings),
        "top3_pct": top3, "top10_pct": top10, "hhi": hhi,
        "industry_dist": ind_dist, "avg_pe": avg_pe, "avg_pb": avg_pb,
        "holdings": [{"name": it["name"], "code": it["code"], "pct": it["pct"],
                      "industry": it.get("industry", "—"),
                      "pe": it.get("pe"), "pb": it.get("pb")} for it in holdings],
    }
    return {
        "ok": True, "name": name, "code": code, "date": h.get("date"),
        "holdings": holdings, "metrics": metrics, "fund_pack": fund_pack,
        "source": "东方财富 fundf10 前十大重仓股（公开数据，仅供研究）",
        "updated_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _fmt_money(x):
    try:
        v = float(x)
    except Exception:
        return None
    if abs(v) >= 1e8:
        return f"{v/1e8:+.2f}亿"
    if abs(v) >= 1e4:
        return f"{v/1e4:+.2f}万"
    return f"{v:+.0f}"


if __name__ == "__main__":
    print(json.dumps(collect_all("贵州茅台"), ensure_ascii=False, indent=2))
