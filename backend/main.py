"""
智投研 AI · FastAPI 后端入口
真实数据(AKShare) + 真实大模型(DeepSeek) 驱动六阶段分析。
运行：uvicorn main:app --reload --port 8000
"""
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import data_center
import ai_committee

load_dotenv()

app = FastAPI(title="智投研 AI", version="1.0")
print(f"[startup] 智投研 AI backend starting; model={os.getenv('DEEPSEEK_MODEL')}")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


class AnalyzeReq(BaseModel):
    query: str
    fast: bool = False


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
    """完整六阶段：真实数据 + DeepSeek 委员会。"""
    data = data_center.collect_all(req.query)
    if not data.get("ok"):
        return JSONResponse(data, status_code=404)
    name = data["symbol"]["name"]
    committee = ai_committee.run_committee(data["data_pack"], name, fast=req.fast)
    data["committee"] = committee
    return JSONResponse(data)


# 挂载前端静态文件（放最后，避免覆盖 /api）
_FRONT = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_FRONT):
    app.mount("/", StaticFiles(directory=_FRONT, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    _port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host=os.getenv("HOST", "0.0.0.0"), port=_port)
