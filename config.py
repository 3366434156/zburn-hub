"""zburn-hub 配置：全部走环境变量，默认值对准 zcode-hub 网关的部署布局。

  BURNER_SUP_DIR     续派文件协议目录（next-prompt.txt / continue.enabled 所在），
                     默认指向 zcode-hub 网关的 data/_sup —— 与外部 Stop 钩子共用。
  BURNER_DATA_DIR    本服务自己的数据目录（queue.json / state.json / 日志）。
  BURNER_PORT        HTTP 端口（默认 8791，绑定 127.0.0.1）。
  BURNER_ADMIN_KEY   后台管理密钥（默认随机生成一次并写入 data/admin-key.txt）。
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _path(env: str, default: str) -> Path:
    raw = (os.getenv(env) or "").strip()
    return Path(raw) if raw else Path(default)


# 续派文件协议目录：默认对准 zcode-hub 网关的 data/_sup（Stop 钩子读的就是它）
SUP_DIR = _path("BURNER_SUP_DIR", r"E:\数据\AI\zcode2api\data\_sup")
# 本服务数据目录
DATA_DIR = _path("BURNER_DATA_DIR", str(_HERE / "data"))
# 服务端口与绑定地址
PORT = int(os.getenv("BURNER_PORT", "8791"))
HOST = os.getenv("BURNER_HOST", "127.0.0.1")
# 后台密钥：env 优先；否则首次启动生成随机值落盘，之后以文件为准
ADMIN_KEY = (os.getenv("BURNER_ADMIN_KEY") or "").strip()
_KEY_FILE = DATA_DIR / "admin-key.txt"


def admin_key() -> str:
    global ADMIN_KEY
    if ADMIN_KEY:
        return ADMIN_KEY
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if _KEY_FILE.exists():
            ADMIN_KEY = _KEY_FILE.read_text(encoding="utf-8").strip()
        if not ADMIN_KEY:
            ADMIN_KEY = secrets.token_urlsafe(24)
            _KEY_FILE.write_text(ADMIN_KEY, encoding="utf-8")
    except Exception:
        ADMIN_KEY = "burner"
    return ADMIN_KEY
