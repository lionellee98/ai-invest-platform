"""
持仓截图 OCR
============
接收图片上传，调用 DeepSeek 视觉能力提取持仓列表。
重点解决「部分图片识别不了」的问题：
- 无损 PNG 优先，避免有损压缩吃掉小字；自动控体积 (<3MB)。
- max_tokens 放大到 4000，避免持仓多时 JSON 被截断。
- 双策略重试：先 json_object，失败/为空再纯文本。
- 健壮 JSON 解析：能从截断 JSON、单条对象里尽力抽取持仓。
失败时返回可人工补录的占位结果，避免前端卡死。
"""
import base64
import io
import json
import os
import re

import ai_committee


try:
    from PIL import Image
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False


_OCR_PROMPT = """你是一位专业的投资持仓截图识别助手。请仔细识别图片中的持仓明细（常见于支付宝/天天基金/同花顺/东方财富/雪球/富途等 App 的持仓、资产、对账单截图）。

请按 JSON 格式输出：
{
  "holdings": [
    {"name": "股票/基金名称", "code": "6位代码或基金代码(如 600519 / 110011)", "type": "股票/基金/ETF/其他", "sector": "消费/新能源/科技/银行/医药/其他", "quantity": 100, "cost": 1.0, "price": 1.2}
  ],
  "note": "对识别不确定或缺失字段的说明"
}
要求：
1. 只输出合法 JSON，不要任何解释文字或 markdown 代码块。
2. 逐行识别，不要遗漏任何一行持仓；表格中每行就是一条 holding。
3. quantity 是数量/份额；cost 是成本价或买入净值；price 是现价/最新净值。
4. 如果某项文字模糊无法识别，仍要列出该 name，其余字段填 null，并在 note 中说明。
5. 如果整张图都不是持仓截图，holdings 为空，note 说明原因。
6. 不要编造具体数值，缺失就填 null。
"""


# ------------------------- 图像预处理 -------------------------
def _detect_mime(path: str) -> str:
    with open(path, "rb") as f:
        head = f.read(12)
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


def _prepare_image(path: str, max_side: int = 2000, max_bytes: int = 3_000_000):
    """返回 (bytes, mime)。无损 PNG 优先，超体积再退 JPEG 并进一步缩小。"""
    mime = _detect_mime(path)
    if not _HAS_PIL:
        with open(path, "rb") as f:
            return f.read(), mime

    img = Image.open(path)
    img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > max_side:
        ratio = max_side / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

    # 先试无损 PNG（对文字最友好）
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()

    if len(data) > max_bytes:
        data, mime = _to_jpeg_within(img, w, h, max_bytes)
    return data, mime


def _to_jpeg_within(img, w, h, max_bytes, quality=90, side=2000):
    side = min(side, max(w, h))
    while side >= 800:
        if max(w, h) > side:
            r = side / max(w, h)
            i = img.resize((int(w * r), int(h * r)), Image.LANCZOS)
        else:
            i = img
        buf = io.BytesIO()
        i.save(buf, format="JPEG", quality=quality)
        data = buf.getvalue()
        if len(data) <= max_bytes:
            return data, "image/jpeg"
        side = int(side * 0.85)
    # 兜底：最小体积 JPEG
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue(), "image/jpeg"


# ------------------------- 调用视觉模型 -------------------------
def _call_vision(b64: str, mime: str, use_json: bool) -> str:
    client = ai_committee._get_client()
    messages = [
        {"role": "system", "content": "你是持仓截图识别助手，只输出 JSON。"},
        {"role": "user", "content": [
            {"type": "text", "text": _OCR_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ]},
    ]
    kwargs = dict(
        model=ai_committee._DEEPSEEK_MODEL,
        messages=messages,
        temperature=0.2,
        max_tokens=4000,
        timeout=90,
    )
    if use_json:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


# ------------------------- 健壮 JSON 解析 -------------------------
def _extract_json(text: str):
    text = text.strip()
    # 去掉 ``` 代码块包裹
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()
    # 1) 直接解析
    try:
        return json.loads(text)
    except Exception:
        pass
    # 2) 定位 {"holdings":[...]} 并做括号配平提取
    m = re.search(r'\{\s*"holdings"\s*:\s*\[', text)
    if m:
        start = m.start()
        depth = 0
        in_str = False
        esc = False
        end = -1
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
        if end > start:
            candidate = text[start:end + 1]
            try:
                return json.loads(candidate)
            except Exception:
                pass
    # 3) 贪婪取首个完整 {...}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def _extract_individual_holdings(text: str):
    """从残缺文本里抠出所有含 name 的扁平对象（应对截断）。"""
    out = []
    for m in re.finditer(r'\{[^{}]*"name"[^{}]*\}', text, re.DOTALL):
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict) and obj.get("name"):
                out.append(obj)
        except Exception:
            pass
    return out


def _parse_holdings(parsed):
    if isinstance(parsed, dict):
        raw = parsed.get("holdings") or []
    elif isinstance(parsed, list):
        raw = parsed
    else:
        raw = []
    holdings = []
    for h in raw:
        if not isinstance(h, dict):
            continue
        name = (h.get("name") or "").strip()
        if not name:
            continue
        holdings.append({
            "name": name,
            "code": str(h.get("code", "")).strip() if h.get("code") else "",
            "type": str(h.get("type", "股票")).strip(),
            "sector": str(h.get("sector", "其他")).strip(),
            "quantity": _num(h.get("quantity")),
            "cost": _num(h.get("cost")),
            "price": _num(h.get("price")),
        })
    return holdings


def _num(v):
    try:
        return float(v) if v is not None else 0.0
    except Exception:
        return 0.0


# ------------------------- 文本结构化（真实可用路径） -------------------------
# 说明：DeepSeek 当前模型(deepseek-v4-flash)的 OpenAI 兼容接口不支持 image_url
# 视觉输入，因此改用「浏览器端 OCR 提取文字 -> 后端文本模型结构化」的稳妥方案。
_STRUCTURE_PROMPT = """你是一位投资持仓文本解析助手。下面是从一张持仓截图用 OCR 提取出的原始文字（可能包含表格、多余空格、换行与噪声）。请从中解析出每一条持仓记录，按 JSON 输出：
{
  "holdings": [
    {"name": "股票/基金名称", "code": "6位代码或基金代码(如 600519 / 110011)", "type": "股票/基金/ETF/其他", "sector": "消费/新能源/科技/银行/医药/其他", "quantity": 100, "cost": 1.0, "price": 1.2}
  ],
  "note": "对识别不确定或缺失字段的说明"
}
要求：
1. 只输出合法 JSON，不要解释文字或 markdown。
2. 逐行解析，不要把一行拆成多条，也不要遗漏。
3. quantity 是数量/份额；cost 是成本价或买入净值；price 是现价/最新净值。
4. 无法判断的字段填 null，不要编造数值；缺失均值可用成本≈现价。
5. 不是持仓文本时 holdings 为空并在 note 说明。
"""


def structure_text(text: str) -> dict:
    """接收 OCR 提取出的原始文本，用文本模型结构化为持仓。返回 {ok, holdings, note, error?}"""
    if not text or not text.strip():
        return {"ok": False, "holdings": [], "note": "没有可解析的文本", "error": "empty text"}
    try:
        client = ai_committee._get_client()
        resp = client.chat.completions.create(
            model=ai_committee._DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是持仓文本解析助手，只输出 JSON。"},
                {"role": "user", "content": _STRUCTURE_PROMPT + "\n\n原始 OCR 文本：\n" + text},
            ],
            temperature=0.2,
            max_tokens=2000,
            response_format={"type": "json_object"},
            timeout=60,
        )
        content = resp.choices[0].message.content or ""
        parsed = _extract_json(content) or {"holdings": [], "note": "模型返回无法解析"}
        holdings = _parse_holdings(parsed)
        return {
            "ok": True,
            "holdings": holdings,
            "note": parsed.get("note", "") if isinstance(parsed, dict) else "",
            "error": None,
        }
    except Exception as e:
        return {"ok": False, "holdings": [], "note": "解析失败", "error": str(e)}


# ------------------------- 主入口 -------------------------
def recognize_screenshot(image_path: str) -> dict:
    """返回 {ok, holdings, note, error?}"""
    try:
        data, mime = _prepare_image(image_path)
    except Exception as e:
        return {"ok": False, "holdings": [], "note": "图片读取失败，请确认是 JPG/PNG 格式", "error": str(e)}

    # Base64 过大可能被拒，给出友好提示
    if len(data) > 8_000_000:
        return {"ok": False, "holdings": [], "note": "图片体积过大，请压缩或裁剪后重试", "error": "image too large"}

    last_err = None
    for attempt in range(2):
        try:
            use_json = (attempt == 0)
            content = _call_vision(base64.b64encode(data).decode("utf-8"), mime, use_json)
            parsed = _extract_json(content)
            if parsed is None:
                blocks = _extract_individual_holdings(content)
                if blocks:
                    parsed = {"holdings": blocks, "note": "已尽力从返回文本中提取单条持仓"}
            if parsed is None:
                parsed = {"holdings": [], "note": "模型返回无法解析，可能持仓较多被截断"}
            holdings = _parse_holdings(parsed)
            if holdings or attempt == 1:
                return {
                    "ok": True,
                    "holdings": holdings,
                    "note": parsed.get("note", "") if isinstance(parsed, dict) else "",
                    "error": None,
                }
        except Exception as e:
            last_err = str(e)
            # 若因 response_format 报错，直接进入纯文本重试
            continue
    return {"ok": False, "holdings": [], "note": "识别失败，可手动添加", "error": last_err}
