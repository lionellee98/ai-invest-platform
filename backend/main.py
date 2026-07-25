"""
智投研 AI · FastAPI 后端入口
真实数据(AKShare) + 真实大模型(DeepSeek) 驱动六阶段分析。
运行：uvicorn main:app --reload --port 8000
"""
import os
import shutil
import tempfile

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import data_center
import ai_committee
import users
import ocr

load_dotenv()

app = FastAPI(title="智投研 AI", version="1.0")
print(f"[startup] 智投研 AI backend starting; model={os.getenv('DEEPSEEK_MODEL')}")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


class AnalyzeReq(BaseModel):
    query: str
    fast: bool = False


class RegisterReq(BaseModel):
    username: str
    password: str


class LoginReq(BaseModel):
    username: str
    password: str


class PortfolioItem(BaseModel):
    name: str
    code: str = ""
    type: str = "股票"
    sector: str = "其他"
    quantity: float
    cost: float
    price: float


class UpdateItem(BaseModel):
    name: str = None
    code: str = None
    type: str = None
    sector: str = None
    quantity: float = None
    cost: float = None
    price: float = None


class AddPosition(BaseModel):
    quantity: float
    price: float


def _get_username(authorization: str = Header(None)) -> str:
    """简易 token：直接传 username。生产环境应替换为 JWT。"""
    if not authorization:
        raise HTTPException(status_code=401, detail="未登录")
    # 支持 "Bearer username" 或纯 username
    user = authorization.replace("Bearer ", "").strip()
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    return user


@app.get("/api/health")
def health():
    return {"ok": True, "model": os.getenv("DEEPSEEK_MODEL"),
            "data_source": data_center.SOURCE_TAG}


@app.get("/api/quote")
def quote(query: str):
    """只拉真实数据（Stage 1），不调用大模型，秒级返回。"""
    return JSONResponse(data_center.collect_all(query))


@app.post("/api/analyze")
def analyze(req: AnalyzeReq):
    """完整分析：股票/ETF 走六阶段真实数据；基金自动降级为前十大重仓股分析。"""
    sym = data_center.resolve_symbol(req.query)
    if sym:
        data = data_center.collect_all(req.query)
        # 只有拿到真实行情价才走股票六阶段；否则（如场外基金）降级
        if data.get("ok") and data["data_pack"].get("price"):
            name = data["symbol"]["name"]
            committee = ai_committee.run_committee(data["data_pack"], name, fast=req.fast)
            data["committee"] = committee
            return JSONResponse(data)
    # 基金降级分析
    fnd = data_center.collect_fund_analysis(req.query)
    if fnd.get("ok"):
        committee = ai_committee.run_fund_committee(fnd["fund_pack"], fnd["name"], fast=req.fast)
        return JSONResponse({
            "ok": True, "degraded": True, "kind": "fund",
            "name": fnd["name"], "code": fnd["code"],
            "fund": {
                "date": fnd.get("date"), "holdings": fnd["holdings"],
                "metrics": fnd["metrics"], "source": fnd.get("source"),
                "updated_at": fnd.get("updated_at"),
            },
            "committee": committee,
        })
    return JSONResponse({
        "ok": False,
        "error": "未能获取该标的的分析数据。若为基金，前十大重仓股接口可能暂不可用（公开数据源限流），请稍后重试；若为股票，请确认代码/名称正确。",
        "hint": "支持：股票/ETF 代码或名称、公募基金代码或名称（自动降级分析重仓股）",
    }, status_code=404)


@app.post("/api/auth/register")
def register(req: RegisterReq):
    return users.register_user(req.username, req.password)


@app.post("/api/auth/login")
def login(req: LoginReq):
    return users.login_user(req.username, req.password)


@app.get("/api/portfolio")
def get_portfolio(authorization: str = Header(None)):
    user = _get_username(authorization)
    return users.get_portfolio(user)


@app.post("/api/portfolio")
def add_item(req: PortfolioItem, authorization: str = Header(None)):
    user = _get_username(authorization)
    return users.add_portfolio_item(user, req.model_dump())


@app.put("/api/portfolio/{item_id}")
def update_item(item_id: str, req: UpdateItem, authorization: str = Header(None)):
    user = _get_username(authorization)
    return users.update_portfolio_item(user, item_id, req.model_dump(exclude_none=True))


@app.delete("/api/portfolio/{item_id}")
def delete_item(item_id: str, authorization: str = Header(None)):
    user = _get_username(authorization)
    return users.delete_portfolio_item(user, item_id)


@app.post("/api/portfolio/{item_id}/add")
def add_to_position(item_id: str, req: AddPosition, authorization: str = Header(None)):
    user = _get_username(authorization)
    return users.add_to_position(user, item_id, req.quantity, req.price)


@app.post("/api/upload/ocr")
async def upload_ocr(file: UploadFile = File(...), authorization: str = Header(None)):
    user = _get_username(authorization)
    suffix = os.path.splitext(file.filename or ".jpg")[1].lower() or ".jpg"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        shutil.copyfileobj(file.file, tmp)
        tmp.close()
        result = ocr.recognize_screenshot(tmp.name)
        # 自动导入识别结果到用户组合
        imported = []
        for h in result.get("holdings", []):
            r = users.upsert_by_symbol(user, h)
            if r.get("ok"):
                imported.append(r.get("item"))
        result["imported"] = imported
        result["import_count"] = len(imported)
        return result
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


class OcrTextReq(BaseModel):
    text: str


@app.post("/api/ocr/structure")
def ocr_structure(req: OcrTextReq, authorization: str = Header(None)):
    """接收 OCR 提取出的原始文本，用文本模型结构化为持仓并自动导入。"""
    user = _get_username(authorization)
    result = ocr.structure_text(req.text)
    if result.get("ok"):
        imported = []
        for h in result.get("holdings", []):
            r = users.upsert_by_symbol(user, h)
            if r.get("ok"):
                imported.append(r.get("item"))
        result["imported"] = imported
        result["import_count"] = len(imported)
    return result


# 挂载前端静态文件（放最后，避免覆盖 /api）
_FRONT = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_FRONT):
    app.mount("/", StaticFiles(directory=_FRONT, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    _port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host=os.getenv("HOST", "0.0.0.0"), port=_port)
