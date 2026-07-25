import json
from fastapi.testclient import TestClient
import main

c = TestClient(main.app)
print("== health ==")
r = c.get("/api/health")
print(r.status_code, r.json())

print("== analyze (TestClient, in-process) ==")
r = c.post("/api/analyze", json={"query": "招商银行", "fast": True})
print("status:", r.status_code)
try:
    j = r.json()
    print("ok:", j.get("ok"), "| symbol:", (j.get("symbol") or {}).get("name"))
    com = j.get("committee") or {}
    print("committee ok:", com.get("ok"), "| verdict:", (com.get("verdict") or {}).get("action"))
except Exception as e:
    print("parse err:", e, r.text[:500])
