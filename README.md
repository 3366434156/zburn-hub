# zburn-hub

**任务工单独立派发服务**（通用续派引擎，着色器项目是它的第一个使用者）——把任意"继续干活"工单排队、按序派给 ZCode 会话、
按 watch 文件变化 + verify 命令做验收，全部通过文件协议完成，不依赖窗口焦点。

是 [zcode-hub](https://github.com/3366434156/zcode-hub)（ZCode 账号池 + 双协议网关）的伴生小服务；
血统来自已封存的 zburn 项目（MIT），本仓同为 MIT。

## 工作原理

```
zburn-hub（本服务）                      ZCode 会话
  工单队列 queue.json                    （着色器项目里干活）
      │ 派单：写指令到                        ▲
      ▼                                       │ Stop 钩子在回合结束
  data/_sup/next-prompt.txt ──────────▶ 一次性消费并归档
  data/_sup/continue.enabled  ←─ 总闸：删掉/改名 = 立即全停
      │ 验收：watch 文件 mtime 变化 → 跑 verify 命令
      ▼
  done / failed（tries 未超限则重新排队）
```

- 派单是**一次性的**：上一条指令被会话消费（回合结束）后才派下一单，不会连续轰炸
- 循环模式（烧额度）必须显式建 `continue.loop` 文件，默认关闭
- 网关 zcode-hub 的「设置页 · 续派监督」卡片与本服务操作的是**同一组文件**，两边都能开关

## 快速开始

```bat
pip install -r requirements.txt
set BURNER_SUP_DIR=E:\数据\AI\zcode2api\data\_sup
python main.py
```

打开 http://127.0.0.1:8791 ，粘贴启动输出里的后台密钥（`data/admin-key.txt`）即可。

## 续派白名单（防劫持，20261101）

Stop 钩子只对 `_sup\continue.projects` 里列出的项目根目录下的会话续派（一行一个路径，`#` 注释）。
**文件不存在或为空 = 不对任何会话续派**——其他对话任务完成时绝不会被强行拉进工单。
总闸 `continue.enabled` 与本服务的工单队列是两层独立开关：有额度≠有任务，没工单就什么都不发生。

## 配置（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `BURNER_SUP_DIR` | `E:\数据\AI\zcode2api\data\_sup` | 文件协议目录，须与 Stop 钩子读的一致 |
| `BURNER_DATA_DIR` | `<本仓>/data` | 队列/状态/密钥存放 |
| `BURNER_PORT` / `BURNER_HOST` | `8791` / `127.0.0.1` | 服务监听 |
| `BURNER_ADMIN_KEY` | 首次随机生成 | 后台密钥（写入 `data/admin-key.txt`） |

## License

MIT
