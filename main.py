"""zburn-hub：任务工单独立派发服务。

  python main.py            # 启动（默认 127.0.0.1:8791）
  网页                      # http://127.0.0.1:8791/（Bearer 密钥首次启动自动生成，
                            #   存于 data/admin-key.txt，网页里粘贴一次即可）
  GET  /admin/api/state     # 队列+状态+轮询快照
  POST /admin/api/enqueue   # 入队 {title, prompt, watch?, verify_cmd?, cwd?, retries?}
  POST /admin/api/order/{id}/cancel | /retry
  POST /admin/api/dispatch-now | /clear-done
  GET  /admin/api/supervisor            # 续派总闸/循环/待发指令状态（读 _sup）
  POST /admin/api/supervisor/enabled    # {enabled: bool} 总闸
  POST /admin/api/supervisor/loop       # {loop: bool} 循环模式（烧额度，慎用）
  POST /admin/api/supervisor/prompt     # {text} 直接下发一次性指令（不经队列）
"""

from __future__ import annotations

import hmac
import pathlib

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

import burner_core, config
from runner import runner

app = FastAPI(title="zburn-hub", version="1.0.0",
              docs_url=None, redoc_url=None, openapi_url=None)


# ── 鉴权：Bearer 对比本地密钥（单用户本地服务，失败不限速）──────────────────
async def verify_key(request: Request) -> None:
    key = config.admin_key()
    if not key:
        return
    auth = request.headers.get("Authorization", "")
    supplied = auth[7:].strip() if auth.startswith("Bearer ") else request.query_params.get("app_key", "")
    if not supplied or not hmac.compare_digest(supplied, key):
        raise HTTPException(401, "密钥不对")


# ── 页面 ────────────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def index():
    page = pathlib.Path(__file__).resolve().parent / "static" / "index.html"
    return FileResponse(page, headers={"Cache-Control": "no-store"})


@app.get("/meta", include_in_schema=False)
async def meta():
    return {"version": app.version, "name": "zburn-hub"}


# ── 鉴权异常统一 JSON 输出 ──────────────────────────────────────────────────
@app.exception_handler(HTTPException)
async def http_exc(request: Request, exc: HTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


# ── 工单接口 ────────────────────────────────────────────────────────────────
@app.get("/admin/api/state", dependencies=[Depends(verify_key)])
async def state():
    snap = burner_core.snapshot()
    snap["poller"] = runner.status()
    return snap


@app.post("/admin/api/enqueue", dependencies=[Depends(verify_key)])
async def enqueue(payload: dict = Body(...)):
    try:
        order = burner_core.enqueue(
            title=str(payload.get("title") or ""),
            prompt=str(payload.get("prompt") or ""),
            watch=list(payload.get("watch") or []),
            verify_cmd=str(payload.get("verify_cmd") or ""),
            cwd=str(payload.get("cwd") or ""),
            retries=int(payload.get("retries") or 0),
        )
    except ValueError as err:
        raise HTTPException(400, str(err)) from None
    return {"ok": True, "order": order}


@app.post("/admin/api/order/{order_id}/cancel", dependencies=[Depends(verify_key)])
async def cancel(order_id: str):
    try:
        return {"ok": True, "order": burner_core.cancel(order_id)}
    except ValueError as err:
        raise HTTPException(404, str(err)) from None


@app.post("/admin/api/order/{order_id}/retry", dependencies=[Depends(verify_key)])
async def retry(order_id: str):
    try:
        return {"ok": True, "order": burner_core.retry(order_id)}
    except ValueError as err:
        raise HTTPException(404, str(err)) from None


@app.post("/admin/api/dispatch-now", dependencies=[Depends(verify_key)])
async def dispatch_now():
    return {"ok": True, **burner_core.tick(force=True)}


@app.post("/admin/api/clear-done", dependencies=[Depends(verify_key)])
async def clear_done():
    return {"ok": True, "removed": burner_core.clear_done()}


# ── 续派总闸（与 zcode-hub 的 /admin/api/supervisor 同一文件协议）───────────
def _read(name: str):
    try:
        return (config.SUP_DIR / name).read_text(encoding="utf-8").strip()
    except Exception:
        return None


@app.get("/admin/api/supervisor", dependencies=[Depends(verify_key)])
async def supervisor_status():
    import json
    state = {}
    try:
        state = json.loads((config.SUP_DIR / "hook-state.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    return {
        "enabled": (config.SUP_DIR / "continue.enabled").exists(),
        "loop": (config.SUP_DIR / "continue.loop").exists(),
        "prompt": _read("next-prompt.txt"),
        "count": state.get("count", 0),
        "lastAt": state.get("lastAt", 0),
    }


@app.post("/admin/api/supervisor/enabled", dependencies=[Depends(verify_key)])
async def supervisor_enabled(payload: dict = Body(...)):
    import time
    flag = config.SUP_DIR / "continue.enabled"
    want = bool(payload.get("enabled", True))
    if want and not flag.exists():
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("", encoding="utf-8")
    elif not want and flag.exists():
        flag.rename(config.SUP_DIR / f"continue.enabled.disabled-{time.strftime('%Y%m%d-%H%M%S')}")
    return {"ok": True, "enabled": flag.exists()}


@app.post("/admin/api/supervisor/loop", dependencies=[Depends(verify_key)])
async def supervisor_loop(payload: dict = Body(...)):
    import time
    flag = config.SUP_DIR / "continue.loop"
    want = bool(payload.get("loop", False))
    if want and not flag.exists():
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("", encoding="utf-8")
    elif not want and flag.exists():
        flag.rename(config.SUP_DIR / f"continue.loop.disabled-{time.strftime('%Y%m%d-%H%M%S')}")
    return {"ok": True, "loop": flag.exists()}


@app.post("/admin/api/supervisor/prompt", dependencies=[Depends(verify_key)])
async def supervisor_prompt(payload: dict = Body(...)):
    text = str(payload.get("text", "")).strip()
    flag = config.SUP_DIR / "next-prompt.txt"
    if text:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(text + "\n", encoding="utf-8")
    elif flag.exists():
        flag.unlink()
    return {"ok": True, "prompt": text or None}


def main() -> None:
    import uvicorn
    runner.start()
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"zburn-hub  http://{config.HOST}:{config.PORT}  "
          f"密钥: {config.DATA_DIR / 'admin-key.txt'}  SUP: {config.SUP_DIR}")
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()
