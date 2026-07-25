"""
持仓截图 OCR
============
接收图片上传，调用 DeepSeek vision 能力提取持仓列表。
失败时返回可人工补录的占位结果，避免前端卡死。
"""
import base64
import json
import os
import re
import tempfile
from typing import Optional

import ai_committee


try:
    from PIL import Image
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False


_OCR_PROMPT = """你是一位专业的投资持仓截图识别助手。请仔细识别图片中的持仓明细，按 JSON 格式输出：
{
  "holdings": [
    {"name": "股票/基金名称", "code": "6位代码或基金代码", "type": "股票/基金/ETF/其他", "sector": "消费/新能源/科技/银行/医药/其他", "quantity": 100, "cost": 1.0, "price": 1.2}
  ],
  "note": "对识别不确定或缺失字段的说明"
}
要求：
1. 只输出合法 JSON，不要任何解释文字或 markdown。
2. quantity 是数量/份额；cost 是成本价或买入净值；price 是现价/最新净值。
3. 如果图片无法识别或不是持仓截图，holdings 为空，note 说明原因。
4. 所有字段缺失时填 null，不要编造具体数值。
"""


def _resize_image(path: str, max_side: int = 1200) -> bytes:
    if not _HAS_PIL:
        with open(path, "rb") as f:
            return f.read()
    try:
        img = Image.open(path)
        img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > max_side:
            ratio = max_side / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = tempfile.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception:
        with open(path, "rb") as f:
            return f.read()


def _mime_ext(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    mapping = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
    return mapping.get(ext, "image/jpeg")


def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[\w]*\n?|\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        # 尝试从文本中找第一个 JSON 对象
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return None


def recognize_screenshot(image_path: str) -> dict:
    """返回 {ok, holdings, note, error?}"""
    try:
        data = _resize_image(image_path)
        b64 = base64.b64encode(data).decode("utf-8")
        mime = _mime_ext(image_path)
        client = ai_committee._get_client()
        resp = client.chat.completions.create(
            model=ai_committee._DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你只输出合法 JSON，不要任何解释文字。"},
                {"role": "user", "content": [
                    {"type": "text", "text": _OCR_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ]},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=1200,
        )
        content = resp.choices[0].message.content
        parsed = _extract_json(content) or {"holdings": [], "note": "模型返回无法解析"}
        holdings = []
        for h in parsed.get("holdings", []):
            if not h.get("name"):
                continue
            holdings.append({
                "name": str(h.get("name", "")),
                "code": str(h.get("code", "")) if h.get("code") else "",
                "type": str(h.get("type", "股票")),
                "sector": str(h.get("sector", "其他")),
                "quantity": _num(h.get("quantity")),
                "cost": _num(h.get("cost")),
                "price": _num(h.get("price")),
            })
        return {"ok": True, "holdings": holdings, "note": parsed.get("note", "")}
    except Exception as e:
        return {"ok": False, "holdings": [], "note": "识别失败，可手动添加", "error": str(e)}


def _num(v):
    try:
        return float(v) if v is not None else 0.0
    except Exception:
        return 0.0
