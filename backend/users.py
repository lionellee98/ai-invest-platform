"""
用户认证与持仓组合持久化
==========================
简易 JSON 文件存储，适合单实例部署演示。生产环境应替换为数据库。
"""
import hashlib
import json
import os
import re
import time
import uuid
from typing import Optional


DATA_PATH = os.getenv("DATA_PATH", os.path.join(os.path.dirname(__file__), "data", "store.json"))
os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)


def _load() -> dict:
    if not os.path.exists(DATA_PATH):
        return {"users": {}, "portfolios": {}, "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"users": {}, "portfolios": {}, "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def _save(db: dict):
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def _hash_pw(password: str) -> str:
    salt = os.urandom(16).hex()
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000).hex()
    return f"{salt}${h}"


def _verify_pw(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split("$")
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000).hex() == h
    except Exception:
        return False


def _valid_username(name: str) -> Optional[str]:
    if not name or len(name) < 3 or len(name) > 20:
        return "用户名长度应为 3-20 位"
    if not re.fullmatch(r"[a-zA-Z0-9_\u4e00-\u9fa5]+", name):
        return "用户名仅支持中英文、数字、下划线"
    return None


def _valid_password(pw: str) -> Optional[str]:
    if not pw or len(pw) < 6:
        return "密码至少 6 位"
    return None


# ----------------------------------------------------------- 用户

def register_user(username: str, password: str) -> dict:
    err = _valid_username(username) or _valid_password(password)
    if err:
        return {"ok": False, "error": err}
    db = _load()
    if username in db["users"]:
        return {"ok": False, "error": "用户名已存在"}
    db["users"][username] = {"password": _hash_pw(password), "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    db["portfolios"][username] = {"items": []}
    _save(db)
    return {"ok": True, "username": username}


def login_user(username: str, password: str) -> dict:
    if not username or not password:
        return {"ok": False, "error": "用户名和密码不能为空"}
    db = _load()
    user = db["users"].get(username)
    if not user or not _verify_pw(password, user["password"]):
        return {"ok": False, "error": "用户名或密码错误"}
    return {"ok": True, "username": username}


def change_password(username: str, old_pw: str, new_pw: str) -> dict:
    err = _valid_password(new_pw)
    if err:
        return {"ok": False, "error": err}
    db = _load()
    user = db["users"].get(username)
    if not user or not _verify_pw(old_pw, user["password"]):
        return {"ok": False, "error": "原密码错误"}
    user["password"] = _hash_pw(new_pw)
    _save(db)
    return {"ok": True}


# ----------------------------------------------------------- 持仓

def _default_portfolio_items():
    # 演示默认持仓，与新用户首次登录体验一致
    return [
        {"id": str(uuid.uuid4())[:8], "name": "贵州茅台", "code": "600519", "type": "股票", "sector": "消费", "quantity": 100, "cost": 1632.50, "price": 1822.30},
        {"id": str(uuid.uuid4())[:8], "name": "宁德时代", "code": "300750", "type": "股票", "sector": "新能源", "quantity": 500, "cost": 210.40, "price": 196.80},
        {"id": str(uuid.uuid4())[:8], "name": "易方达蓝筹精选", "code": "005827", "type": "基金", "sector": "消费", "quantity": 30000, "cost": 2.140, "price": 2.386},
        {"id": str(uuid.uuid4())[:8], "name": "华夏新能源ETF", "code": "516160", "type": "ETF", "sector": "新能源", "quantity": 60000, "cost": 1.024, "price": 0.958},
        {"id": str(uuid.uuid4())[:8], "name": "招商银行", "code": "600036", "type": "股票", "sector": "银行", "quantity": 1200, "cost": 33.20, "price": 38.65},
        {"id": str(uuid.uuid4())[:8], "name": "中际旭创", "code": "300308", "type": "股票", "sector": "科技", "quantity": 300, "cost": 98.60, "price": 121.40},
    ]


def get_portfolio(username: str) -> dict:
    db = _load()
    pf = db["portfolios"].get(username)
    if not pf or not pf.get("items"):
        pf = {"items": _default_portfolio_items()}
        db["portfolios"][username] = pf
        _save(db)
    return {"ok": True, "items": pf["items"]}


def _calc(item: dict):
    q = float(item.get("quantity", 0) or 0)
    cost = float(item.get("cost", 0) or 0)
    price = float(item.get("price", 0) or 0)
    item["market_value"] = round(q * price, 2)
    item["cost_value"] = round(q * cost, 2)
    item["pnl"] = round(item["market_value"] - item["cost_value"], 2)
    item["pnl_pct"] = round((price - cost) / cost * 100, 2) if cost else 0.0


def _ensure_item(item: dict):
    item.setdefault("id", str(uuid.uuid4())[:8])
    item.setdefault("name", "未命名")
    item.setdefault("code", "")
    item.setdefault("type", "股票")
    item.setdefault("sector", "其他")
    item["quantity"] = float(item.get("quantity", 0) or 0)
    item["cost"] = float(item.get("cost", 0) or 0)
    item["price"] = float(item.get("price", 0) or 0)
    _calc(item)
    return item


def add_portfolio_item(username: str, item: dict) -> dict:
    db = _load()
    pf = db["portfolios"].setdefault(username, {"items": []})
    item = _ensure_item(item)
    pf["items"].append(item)
    _save(db)
    return {"ok": True, "item": item}


def update_portfolio_item(username: str, item_id: str, updates: dict) -> dict:
    db = _load()
    pf = db["portfolios"].get(username)
    if not pf:
        return {"ok": False, "error": "未找到组合"}
    for it in pf["items"]:
        if it["id"] == item_id:
            for k in ["name", "code", "type", "sector"]:
                if k in updates:
                    it[k] = updates[k]
            for k in ["quantity", "cost", "price"]:
                if k in updates:
                    it[k] = float(updates[k] or 0)
            _calc(it)
            _save(db)
            return {"ok": True, "item": it}
    return {"ok": False, "error": "未找到持仓记录"}


def delete_portfolio_item(username: str, item_id: str) -> dict:
    db = _load()
    pf = db["portfolios"].get(username)
    if not pf:
        return {"ok": False, "error": "未找到组合"}
    pf["items"] = [it for it in pf["items"] if it["id"] != item_id]
    _save(db)
    return {"ok": True}


def add_to_position(username: str, item_id: str, quantity: float, price: float) -> dict:
    db = _load()
    pf = db["portfolios"].get(username)
    if not pf:
        return {"ok": False, "error": "未找到组合"}
    quantity = float(quantity or 0)
    price = float(price or 0)
    if quantity <= 0 or price <= 0:
        return {"ok": False, "error": "加仓数量和价格必须大于 0"}
    for it in pf["items"]:
        if it["id"] == item_id:
            old_q = float(it.get("quantity", 0) or 0)
            old_cost = float(it.get("cost", 0) or 0)
            total_q = old_q + quantity
            total_cost = old_q * old_cost + quantity * price
            it["quantity"] = round(total_q, 4)
            it["cost"] = round(total_cost / total_q, 4) if total_q else old_cost
            _calc(it)
            _save(db)
            return {"ok": True, "item": it}
    return {"ok": False, "error": "未找到持仓记录"}


def upsert_by_symbol(username: str, item: dict) -> dict:
    """OCR 导入时按代码合并，避免重复添加。"""
    db = _load()
    pf = db["portfolios"].setdefault(username, {"items": []})
    code = item.get("code", "")
    if code:
        for it in pf["items"]:
            if it["code"] == code:
                # 合并：数量相加，成本加权
                old_q = float(it.get("quantity", 0) or 0)
                old_cost = float(it.get("cost", 0) or 0)
                add_q = float(item.get("quantity", 0) or 0)
                add_cost = float(item.get("cost", 0) or 0)
                total_q = old_q + add_q
                if total_q > 0:
                    it["quantity"] = round(total_q, 4)
                    it["cost"] = round((old_q * old_cost + add_q * add_cost) / total_q, 4)
                if item.get("price"):
                    it["price"] = float(item["price"])
                if item.get("name"):
                    it["name"] = item["name"]
                if item.get("sector"):
                    it["sector"] = item["sector"]
                _calc(it)
                _save(db)
                return {"ok": True, "item": it, "merged": True}
    item = _ensure_item(item)
    pf["items"].append(item)
    _save(db)
    return {"ok": True, "item": item, "merged": False}
