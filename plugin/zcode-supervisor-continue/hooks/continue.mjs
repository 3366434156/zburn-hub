/**
 * ZCode Stop 钩子 v0.2 —— 一次性续派（用户语义修正版 20261031）
 *
 * 与 v0.1 的区别（用户指令："网关关这边也关、某些情况只需要继续、不是消耗完 token"）：
 * 1. 删除内置兜底文案：没有 next-prompt.txt 就什么都不注入（v0.1 会注入"不设数量上限"
 *    的内置文案无限烧额度——本次事故根源）；
 * 2. next-prompt.txt 变为一次性：注入一次后立即归档为 next-prompt.used-<时间>.txt，
 *    同一文案不会反复注入；
 * 3. 循环续派改为显式 opt-in：只有存在 continue.loop 文件时才会连续续派，
 *    且也必须有 next-prompt.txt 提供文案（没有就停）；
 * 4. 网关侧总开关不变：删掉 continue.enabled = 立即全停（每次触发都重查）；
 *    网关读不到 / 额度低于阈值 = 停。
 *
 * 开关一览（都在 E:\数据\AI\zcode-hub\data\_sup\）：
 *   continue.enabled   存在=插件可用，删除=立即全停（总闸）
 *   continue.loop      存在=允许循环续派（烧额度模式，慎用），删除=单次模式
 *   next-prompt.txt    本回合要注入的一次性指令，注入后自动归档
 */

import fs from 'node:fs';
import path from 'node:path';

const SUP_DIR = 'E:/数据/AI/zcode-hub/data/_sup';   // 正斜杠：规避 JS 字符串反斜杠转义
const LOG_FILE = path.join(SUP_DIR, 'hook.log');
const STATE_FILE = path.join(SUP_DIR, 'hook-state.json');
const ENABLE_FLAG = path.join(SUP_DIR, 'continue.enabled');
const LOOP_FLAG = path.join(SUP_DIR, 'continue.loop');
const PROMPT_FILE = path.join(SUP_DIR, 'next-prompt.txt');

const GATEWAY = 'http://127.0.0.1:3000';
const ADMIN_KEY = 'zcode';
const STOP_REMAINING = 1_000_000;
const MIN_INTERVAL_MS = 5_000;
const MAX_CONTINUATIONS = 50_000;

function log(msg) {
  try {
    fs.appendFileSync(LOG_FILE, `${new Date().toISOString()} ${msg}\n`);
  } catch {}
}

function readState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
  } catch {
    return { count: 0, lastAt: 0 };
  }
}

function writeState(state) {
  try {
    fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2), 'utf8');
  } catch {}
}

async function quotaRemaining() {
  const res = await fetch(`${GATEWAY}/admin/api/accounts`, {
    headers: { Authorization: `Bearer ${ADMIN_KEY}` },
  });
  if (!res.ok) throw new Error(`gateway ${res.status}`);
  const data = await res.json();
  let total = 0;
  for (const acc of data.accounts || []) {
    if (!acc.enabled) continue;
    for (const q of Object.values(acc.quota || {})) {
      total += Number(q?.remaining || 0);
    }
  }
  return total;
}

/** 读续派白名单：_sup/continue.projects，一行一个项目根（# 注释）。
 *  文件不存在/为空 → 空数组 = 不对任何会话续派（安全默认：宁可不派，不可劫持）。 */
function readProjects() {
  try {
    return fs.readFileSync(path.join(SUP_DIR, 'continue.projects'), 'utf8')
      .split(String.fromCharCode(10)).map(ln => ln.trim())
      .filter(ln => ln && !ln.startsWith('#'))
      .map(ln => {
        const parts = ln.split(String.fromCharCode(92)).join('/');
        return parts.endsWith('/') ? parts.slice(0, -1) : parts.toLowerCase();
      });
  } catch {
    return [];
  }
}

/** 取指令：一次性读 next-prompt.txt；循环模式读后不删；单次模式读后立即归档。
 *  两处都没有 → 返回 null（不注入，这是 v0.2 的核心：不再有内置兜底文案）。 */
function pickPrompt(loopMode) {
  let text = '';
  try {
    text = fs.readFileSync(PROMPT_FILE, 'utf8').trim();
  } catch {
    return null;
  }
  if (!text) return null;
  if (!loopMode) {
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    try {
      fs.renameSync(PROMPT_FILE, path.join(SUP_DIR, `next-prompt.used-${stamp}.txt`));
      log(`一次性指令已消费并归档（next-prompt.used-${stamp}.txt）`);
    } catch (err) {
      log(`归档失败（${err.message}），本轮仍注入但文件保留，可能重复注入一次`);
    }
  }
  return text;
}

async function main() {
  let payload = '';
  try {
    payload = fs.readFileSync(0, 'utf8');
  } catch {
    payload = '';
  }
  log(`Stop 钩子触发 len=${payload.length}`);

  // 工作区白名单守卫（20261101 用户指令：其他对话任务完成不得被强行拉进续派）：
  // 只读 _sup\continue.projects，一行一个项目根路径（# 开头为注释）。
  // 文件不存在或为空 = 不对任何会话续派（安全默认：宁可不派，不可劫持）。
  let hookCwd = '';
  try { hookCwd = String(JSON.parse(payload).cwd || ''); } catch { hookCwd = ''; }
  hookCwd = hookCwd.split(String.fromCharCode(92)).join('/'); if (hookCwd.endsWith('/')) hookCwd = hookCwd.slice(0, -1); hookCwd = hookCwd.toLowerCase();
  const allowed = readProjects();
  if (!allowed.some(root => hookCwd === root || hookCwd.startsWith(root + '/'))) {
    log(`会话不在白名单（cwd=${hookCwd || '未知'}，白名单 ${allowed.length} 项），放行停止`);
    return;
  }

  // 总闸：网关侧删除 continue.enabled 即全停
  if (!fs.existsSync(ENABLE_FLAG)) {
    log('总闸未开（缺少 continue.enabled），放行停止');
    return;
  }

  const state = readState();
  const now = Date.now();
  if (now - Number(state.lastAt || 0) < MIN_INTERVAL_MS) {
    log('节流：距上次续派不足 5 秒，跳过');
    return;
  }
  if (Number(state.count || 0) >= MAX_CONTINUATIONS) {
    log(`已达续派上限 ${MAX_CONTINUATIONS}，放行停止`);
    return;
  }

  const loopMode = fs.existsSync(LOOP_FLAG);
  const reason = pickPrompt(loopMode);
  if (!reason) {
    log(loopMode
      ? '循环模式但无 next-prompt.txt（v0.2 无兜底文案），放行停止'
      : '单次模式：无 next-prompt.txt，无任务要续，放行停止');
    return;
  }

  // 网关额度闸
  let remaining;
  try {
    remaining = await quotaRemaining();
  } catch (err) {
    log(`读额度失败（${err.message}），放行停止`);
    return;
  }
  if (remaining <= STOP_REMAINING) {
    log(`额度已烧完（剩余 ${remaining}），放行停止`);
    return;
  }

  writeState({ count: Number(state.count || 0) + 1, lastAt: now });
  process.stdout.write(JSON.stringify({ decision: 'block', reason }));
  log(`已续派 #${Number(state.count || 0) + 1}（${loopMode ? '循环' : '单次'}，剩余额度 ${remaining}）`);
}

main().catch((err) => {
  log(`钩子异常：${err?.stack || err}`);
});
