"""
ACP Dashboard - 多智能体协作可视化监控面板
Flask 后端服务 (v0.2 - 接入真实 Copaw API)
"""

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import requests
import re
import json
import time
import os
import functools
from datetime import datetime
from pathlib import Path

# 路径配置
WORKSPACE_DIR = Path(__file__).parent.parent
COPAW_DIR = WORKSPACE_DIR / "_copaw"
TASKS_STATE_FILE = WORKSPACE_DIR / "coordination" / "tasks_state.md"
KNOWLEDGE_DIR = WORKSPACE_DIR / "knowledge"

# Copaw API
COPAW_API = "http://127.0.0.1:8088/api/agents"

# Agent 中文映射
AGENT_NAMES = {
    "default": {"name": "maintainer", "role": "总调度"},
    "mWNCXY": {"name": "dev", "role": "代码开发"},
    "iPt2x8": {"name": "小忆", "role": "资料员"},
    "cxdNEN": {"name": "骐骥", "role": "能力进化"},
    "jzFWyP": {"name": "总管", "role": "流程管理"},
    "XuFfNm": {"name": "小岑", "role": "文档分析"},
    "UKCexb": {"name": "vision", "role": "图像处理"},
    "Z5edzS": {"name": "docs-writer", "role": "调研写作"},
    "hGmevJ": {"name": "执剑者", "role": "安全审计"},
}

EXCLUDE_IDS = {"QwenPaw_QA_Agent_0.2", "CoPaw_QA_Agent_0.1beta1"}

# 文档分类定义 — 支持 id（预定义内容）和 path（知识库文件）
DOCS_CATALOG = [
    # ── 平台总览 ──
    {"id": "intro", "title": "平台介绍", "icon": "fa-info-circle",
     "path": "总纲/index.md", "section": "平台总览"},
    {"id": "agents", "title": "团队成员", "icon": "fa-users",
     "path": "总纲/01_团队成员.md", "section": "平台总览"},
    # ── 核心流程 ──
    {"id": "rules", "title": "最佳实践", "icon": "fa-gavel",
     "path": "协作流程/协作最佳实践.md", "section": "核心流程"},
    {"id": "sop", "title": "任务分配规范", "icon": "fa-sitemap",
     "path": "协作流程/Agent任务分配规范.md", "section": "核心流程"},
    {"id": "tasks", "title": "任务状态机", "icon": "fa-code-branch",
     "path": "协作流程/任务状态机.md", "section": "核心流程"},
    {"id": "review", "title": "复盘粒度分级", "icon": "fa-clipboard-check",
     "path": "协作流程/复盘粒度分级.md", "section": "核心流程"},
    # ── 知识库 ──
    {"id": "knowledge", "title": "高频知识要点", "icon": "fa-lightbulb",
     "path": "总纲/04_高频知识.md", "section": "知识库"},
    {"id": "changelog", "title": "最新入库记录", "icon": "fa-history",
     "path": "总纲/03_最新入库.md", "section": "知识库"},
    # ── 安全与开发 ──
    {"id": "security", "title": "安全审计规范", "icon": "fa-shield-alt",
     "path": "05_安全审计/协作流程升级安全界限规则.md", "section": "安全与开发"},
    {"id": "registry", "title": "Agent 注册表", "icon": "fa-address-book",
     "path": "02_agent_registry/Agent-ID-Registry.md", "section": "安全与开发"},
]

# ======== P1: 后端内存缓存（TTL 8s）========
_cache = {}

def cached_get(key, ttl=8):
    """查询缓存，过期返回 None"""
    now = time.time()
    if key in _cache and (now - _cache[key][0]) < ttl:
        return _cache[key][1]
    return None

def cached_set(key, data):
    """写入缓存（携带时间戳）"""
    _cache[key] = (time.time(), data)


app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
CORS(app)


def get_docs_list():
    """获取文档目录"""
    return [{"id": d["id"], "title": d["title"], "icon": d["icon"], "section": d.get("section", "")} for d in DOCS_CATALOG]


def build_knowledge_tree():
    """递归构建知识库目录树"""
    def _walk(dir_path, rel_path=""):
        children = []
        try:
            for item in sorted(dir_path.iterdir()):
                name = item.name
                # 跳过非文档目录
                if name.startswith('.') or name.startswith('_'):
                    continue
                if item.is_dir():
                    sub = _walk(item, f"{rel_path}/{name}" if rel_path else name)
                    if sub["children"]:  # 非空目录才显示
                        children.append(sub)
                elif item.suffix == '.md':
                    children.append({
                        "name": name.replace('.md', ''),
                        "type": "file",
                        "path": f"{rel_path}/{name}" if rel_path else name
                    })
            return {"type": "dir", "name": dir_path.name if dir_path != KNOWLEDGE_DIR else "根目录", "children": children}
        except Exception:
            return {"type": "dir", "name": "？", "children": []}

    tree = _walk(KNOWLEDGE_DIR)
    # 展开第一层子目录
    for child in tree.get("children", []):
        child["_open"] = child["type"] == "dir" and len(child.get("children", [])) < 10
    return tree


def get_doc_content(doc_id):
    """获取指定文档ID的内容"""
    for d in DOCS_CATALOG:
        if d["id"] == doc_id:
            fp = KNOWLEDGE_DIR / d["path"]
            if fp.exists():
                return {
                    "id": d["id"],
                    "title": d["title"],
                    "path": d["path"],
                    "content": fp.read_text(encoding="utf-8-sig", errors="replace")
                }
    return None


def fetch_copaw_agents():
    """从 Copaw API 获取 Agent 列表（带 TTL 8s 缓存）"""
    cached = cached_get("copaw_agents")
    if cached is not None:
        return cached
    try:
        r = requests.get(COPAW_API, timeout=3)
        if r.status_code == 200:
            raw = r.json().get("agents", [])
            result = []
            for a in raw:
                aid = a["id"]
                if aid in EXCLUDE_IDS:
                    continue
                info = AGENT_NAMES.get(aid, {"name": a.get("name", aid), "role": "Unknown"})
                model_data = a.get("active_model") or {}
                result.append({
                    "id": aid,
                    "name": info["name"],
                    "role": info["role"],
                    "provider": model_data.get("provider_id", "N/A"),
                    "model": model_data.get("model", "N/A"),
                    "status": "online",
                    "tasks": 0,
                })
            cached_set("copaw_agents", (result, None))
            return result, None
        return None, f"API status {r.status_code}"
    except Exception as e:
        return None, str(e)


def parse_tasks_state():
    """从 tasks_state.md 解析任务，同时尝试从任务文件中提取详情（带 TTL 8s 缓存）"""
    cached = cached_get("tasks_state")
    if cached is not None:
        return cached
    if not TASKS_STATE_FILE.exists():
        return None, "tasks_state.md not found"
    try:
        content = TASKS_STATE_FILE.read_text(encoding="utf-8-sig")
        tasks = []

        # 同时从 coordination + _copaw/coordination 目录读取任务详情
        coord_dirs = [WORKSPACE_DIR / "_copaw" / "coordination", WORKSPACE_DIR / "coordination"]
        task_details = {}
        for coord_dir in coord_dirs:
            if not coord_dir.exists():
                continue
            for tf in coord_dir.glob("T-*.md"):
                try:
                    detail = tf.read_text(encoding="utf-8-sig", errors="replace")
                    title_m = re.search(r'^#\s+(.+)', detail, re.MULTILINE)
                    agent_m = re.search(r'(?:Agent|负责人|assignee)\**\s*[：:]\s*(\S+)', detail)
                    priority_m = re.search(r'(?:优先级|priority)\**\s*[：:]\s*(high|medium|low)', detail, re.IGNORECASE)
                    desc_m = re.search(r'(?:描述|description|概述)\**\s*[：:]\s*(.+?)(?:\n|$)', detail, re.IGNORECASE)
                    eta_m = re.search(r'(?:预估耗时|estimated)\**\s*[：:]\s*(\d+)', detail)
                    start_m = re.search(r'(?:开始时间|start)\**\s*[：:]\s*(\d{2}:\d{2})', detail)
                    stage_m = re.search(r'(?:当前阶段|stage)\**\s*[：:]\s*(.+?)(?:\n|$)', detail)
                    task_details[tf.stem] = {
                        "name": title_m.group(1).strip()[:60] if title_m else tf.stem,
                        "agent": agent_m.group(1) if agent_m else "—",
                        "priority": priority_m.group(1).lower() if priority_m else "medium",
                        "desc": desc_m.group(1).strip()[:120] if desc_m else "",
                        "estimated_minutes": int(eta_m.group(1)) if eta_m else None,
                        "start_time": start_m.group(1) if start_m else None,
                        "current_stage": stage_m.group(1).strip() if stage_m else None,
                    }
                except Exception:
                    pass

        # 按 ## 标题分割段落
        for section in re.split(r'\n##\s+', content):
            first_line = section.split('\n')[0]
            if '活跃' in first_line or '进行中' in first_line or '进行' in first_line:
                status = "executing"
                progress = 50
            elif '最近完成' in first_line or '已完成' in first_line or '完成' in first_line:
                status = "completed"
                progress = 100
            elif '取消' in first_line or '废弃' in first_line:
                status = "cancelled"
                progress = 0
            elif '历史' in first_line or '归档' in first_line:
                continue  # 跳过历史归档
            else:
                continue

            for line in section.split('\n'):
                # 扩展正则：捕获第 4 列状态
                m = re.match(r'\|\s*(T-\S+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(\S+?)\s*\|', line)
                table_status = None
                if m:
                    tid = m.group(1)
                    name_raw = m.group(2).strip()
                    table_agent = m.group(3).strip()
                    table_status = m.group(4).strip().lower() if m.lastindex >= 4 else None
                else:
                    m = re.match(r'\|\s*(T-\S+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*', line)
                    if not m:
                        continue
                    tid = m.group(1)
                    name_raw = m.group(2).strip()
                    table_agent = m.group(3).strip()
                # 表格状态列覆盖段落判定（防 pending_review 等非标准状态被误判为 executing）
                final_status = status
                if table_status and ('review' in table_status or 'pending' in table_status or 'wait' in table_status):
                    final_status = "pending"
                elif table_status and 'completed' in table_status:
                    final_status = "completed"
                detail = task_details.get(tid, {})
                # 计算真实进度：实际耗时/预估耗时
                est = detail.get("estimated_minutes")
                st = detail.get("start_time")
                progress = 50
                if final_status == "completed":
                    progress = 100
                elif est and st:
                    try:
                        h, m = map(int, st.split(':'))
                        now = datetime.now()
                        elapsed = (now.hour - h) * 60 + (now.minute - m)
                        if elapsed < 0:
                            elapsed += 24 * 60  # 跨天修正
                        progress = min(95, max(1, round(elapsed / est * 100)))
                    except:
                        pass
                tasks.append({
                    "id": tid,
                    "name": detail.get("name") or name_raw or tid,
                    "agent": detail.get("agent") or table_agent or "—",
                    "status": final_status,
                    "progress": progress,
                    "priority": detail.get("priority", "medium"),
                    "desc": detail.get("desc", ""),
                    "estimated_minutes": est,
                    "start_time": st,
                    "current_stage": detail.get("current_stage"),
                })
        cached_set("tasks_state", (tasks, None))
        return tasks, None
    except Exception as e:
        return None, str(e)


# ── 统计辅助函数 (v0.3) ──

def compute_knowledge_ratio(tasks):
    """统计 knowledge/协作流程/复盘记录/ 下文件数 vs 已完成任务数的比例"""
    review_dir = KNOWLEDGE_DIR / "协作流程" / "复盘记录"
    file_count = 0
    if review_dir.exists():
        file_count = len(list(review_dir.rglob("*.md")))
    completed = len([t for t in tasks if t["status"] == "completed"])
    return round(file_count / max(completed, 1), 2)


def compute_knowledge_trend():
    """按周统计 knowledge/总纲/03_最新入库.md 的入库条数，返回最近8周（标签为日期范围）"""
    changelog_path = KNOWLEDGE_DIR / "总纲" / "03_最新入库.md"
    if not changelog_path.exists():
        return []
    from datetime import datetime as dt_parse, timedelta
    week_data = {}  # key: (year, week_num), value: {dates:[], count:0}
    date_re = re.compile(r'(\d{4}-\d{2}-\d{2})')
    with open(changelog_path, "r", encoding="utf-8") as f:
        for line in f:
            m = date_re.search(line)
            if m:
                d = dt_parse.strptime(m.group(1), "%Y-%m-%d")
                iso = d.isocalendar()
                key = (iso[0], iso[1])
                if key not in week_data:
                    week_data[key] = {"dates": [], "count": 0}
                week_data[key]["dates"].append(d)
                week_data[key]["count"] += 1
    sorted_keys = sorted(week_data.keys())
    result = []
    for key in sorted_keys[-8:]:
        wd = week_data[key]
        monday = min(wd["dates"])
        sunday = monday + timedelta(days=6)
        label = f"{monday.month}/{monday.day}"
        result.append({"week": label, "count": wd["count"]})
    return result


def compute_review_severity():
    """从 03_最新入库.md 的「复盘粒度」列统计 L1/L2/L3 数量"""
    changelog_path = KNOWLEDGE_DIR / "总纲" / "03_最新入库.md"
    severity = {"L1": 0, "L2": 0, "L3": 0}
    if not changelog_path.exists():
        return severity
    sev_re = re.compile(r'[Ll](\d)')
    with open(changelog_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith('|') and '|' in line[1:]:
                # 取最后一列（复盘粒度）
                cols = [c.strip() for c in line.split('|')]
                if len(cols) >= 5:
                    m = sev_re.search(cols[4])
                    if m:
                        key = f"L{m.group(1)}"
                        if key in severity:
                            severity[key] += 1
    return severity


def compute_agent_knowledge_contributions():
    """从 03_最新入库.md 统计各 Agent 近30天的知识贡献次数
    按知识名称中的 Agent 名称关键词匹配"""
    changelog_path = KNOWLEDGE_DIR / "总纲" / "03_最新入库.md"
    if not changelog_path.exists():
        return {}
    
    agent_keywords = {
        "maintainer": ["maintainer"],
        "dev": ["dev"],
        "小忆(rose)": ["小忆", "rose", "Rose"],
        "骐骥": ["骐骥"],
        "总管": ["总管"],
        "小岑": ["小岑"],
        "vision": ["vision"],
        "docs-writer": ["docs-writer"],
        "执剑者": ["执剑者"],
    }
    
    from datetime import datetime as dt_parse, timedelta
    cutoff = dt_parse.now() - timedelta(days=30)
    
    counts = {name: 0 for name in agent_keywords}
    
    with open(changelog_path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r'\|\s*(\d{4}-\d{2}-\d{2})\s*\|', line)
            if not m:
                continue
            try:
                entry_date = dt_parse.strptime(m.group(1), "%Y-%m-%d")
            except ValueError:
                continue
            if entry_date < cutoff:
                continue
            
            for agent_name, keywords in agent_keywords.items():
                for kw in keywords:
                    if kw in line:
                        counts[agent_name] += 1
                        break
    
    return counts


def compute_stats(agents, tasks):
    """计算统计数据"""
    # Agent 健康统计
    healthy = len([a for a in agents if a.get("health") in ("healthy", "online")])
    idle = len([a for a in agents if a.get("health") == "idle"])
    offline = len([a for a in agents if a.get("health") == "offline"])
    return {
        "executing": len([t for t in tasks if t["status"] == "executing"]),
        "pending": len([t for t in tasks if t["status"] in ("pending", "unknown")]),
        "completed": len([t for t in tasks if t["status"] == "completed"]),
        "failed": len([t for t in tasks if t["status"] in ("failed", "cancelled")]),
        "agents_healthy": healthy,
        "agents_idle": idle,
        "agents_offline": offline,
        "agents_total": len(agents),
        "tasks_total": len(tasks),
        "data_source": "live",
    }


def list_all_docs():
    """获取所有知识库文件列表（用于全文搜索）"""
    kb = WORKSPACE_DIR / "knowledge"
    if not kb.exists():
        return []
    docs = []
    for f in sorted(kb.rglob("*.md")):
        rel = str(f.relative_to(kb)).replace("\\", "/")
        if "复盘记录" in rel or "草稿" in rel:
            continue
        docs.append({"path": rel, "name": f.stem, "size": f.stat().st_size})
    return docs


def fix_garbled_text(text):
    """修复常见乱码模式（Latin-1→GBK 双编码损坏）"""
    fixes = {
        # tasks_state.md
        '浠诲姟鐘舵€佽拷韪?': '任务状态追踪',
        '杩涜': '进行',
        '瀹屾垚': '完成',
        '鍙栨秷': '取消',
        '搴熷純': '废弃',
        '澶氭櫤鑳戒綋鍗忎綔鍙鍖栧钩鍙?': '多智能体协作可视化平台',
        '绠＄悊瑙勮寖鍏ュ簱': '管理规范入库',
        '鍙鍖栭潰鏉垮崌绾?': '可视化面板升级',
        '闈欐€侀〉闈㈡洿鏂?': '静态页面更新',
        '缁煎悎骞冲彴妗嗘灦鏋勫缓': '综合平台框架构建',
        '浠诲姟鏂囦欢绠＄悊浣撶郴寤虹珛': '任务文件管理体系建立',
        '娉ㄥ唽琛ㄤ慨姝?': '注册表修正',
        '鍗忎綔娴佺▼浼樺寲': '协作流程优化',
        '瀹屾暣ACP鏋舵瀯': '完整ACP架构',
        '6鍗＄墖绯荤粺': '6卡片系统',
        'CSS鐗堟湰鏇存柊': 'CSS版本更新',
        '鐜颁唬鍖栧鏅鸿兘浣撳崗浣滃钩鍙?': '现代化多智能体协作平台',
        '瑙勮寖鍏ュ簱': '规范入库',
        '淇宸ヤ綔鐩綍': '修正工作目录',
        '鏈€鍚庢洿鏂?': '最后更新',
        '璺熻釜': '追踪',
        '妗嗘灦': '框架',
        # memory files
        '鍥㈤槦鎴愬憳': '团队成员',
        '璁板繂涓庡弽鎬?': '记忆与反思',
        '浜嬪疄璁板繂': '事实记忆',
        '鎶€鏈粏鑺?': '技术细节',
        '鍙嶆€濅笌鏀硅繘': '反思与改进',
        '鐭ヨ瘑搴撶鐞?': '知识库管理',
        '澶嶇洏闂幆': '复盘闭环',
    }
    result = text
    for garbled, correct in fixes.items():
        result = result.replace(garbled, correct)
    return result


def get_recent_logs_from_files():
    """聚合四来源日志：任务流水 + Agent活动 + 事件流 + Dashboard自身"""
    logs = []
    now = datetime.now()

    # ── 1. 任务流水（tasks_state.md）──
    if TASKS_STATE_FILE.exists():
        try:
            content = TASKS_STATE_FILE.read_text(encoding="utf-8-sig")
            # 判断当前在哪个区块
            current_status = ""
            for line in content.split('\n'):
                stripped = line.strip()
                if stripped.startswith('## ') or stripped.startswith('# '):
                    # 尝试从标题推断状态
                    current_status = stripped.lstrip('#').strip()
                    continue
                m = re.match(r'\|\s*(T-\S+)\s*\|\s*(.+?)\s*\|\s*', stripped)
                if m:
                    tid, name = m.group(1), m.group(2)
                    # 从区段标题或任务行内容推断状态
                    if '完成' in current_status or 'completed' in current_status.lower():
                        cat, lvl = '任务', 'INFO'
                    elif '取消' in current_status or '废弃' in current_status:
                        cat, lvl = '任务', 'WARNING'
                    elif '进行' in current_status or 'executing' in current_status.lower():
                        cat, lvl = '任务', 'INFO'
                    else:
                        cat, lvl = '任务', 'INFO'
                    logs.append({"time": "2026-04-22 00:00:00",
                                 "level": lvl, "source": "Tasks",
                                 "category": cat, "message": f"[{current_status[:20]}] {tid} {name}"})
        except Exception:
            pass

    # ── 2. Agent 活动（memory/*.md）──
    memory_dir = WORKSPACE_DIR / "memory"
    if memory_dir.exists():
        mem_files = sorted(memory_dir.glob("20*.md"), reverse=True)[:7]
        for mf in mem_files:
            try:
                txt = mf.read_text(encoding="utf-8-sig", errors="replace")
                date_str = mf.stem
                sections = re.split(r'\n(?:#{2,3})\s+', txt)
                for sec in sections:
                    lines = sec.strip().split('\n')
                    if not lines: continue
                    title = lines[0].strip()
                    for ln in lines[1:]:
                        if ln.startswith('- ') or ln.startswith('* '):
                            msg = ln.lstrip('-* ').strip()
                            if len(msg) > 6:
                                logs.append({"time": f"{date_str} 00:00:00",
                                             "level": "INFO", "source": "Agent",
                                             "category": "Agent",
                                             "message": f"[{title[:25]}] {msg[:140]}"})
            except Exception:
                pass

    # ── 3. 知识库事件流 ──
    changelog = WORKSPACE_DIR / "knowledge" / "总纲" / "03_最新入库.md"
    if changelog.exists():
        try:
            txt = changelog.read_text(encoding="utf-8-sig", errors="replace")
            for line in txt.split('\n'):
                m = re.match(r'^[-*]\s*(20\d{2}-\d{2}-\d{2})[:：]\s*(.+)', line)
                if m:
                    logs.append({"time": f"{m.group(1)} 00:00:00", "level": "INFO",
                                 "source": "Knowledge", "category": "知识库",
                                 "message": m.group(2)[:150]})
        except Exception:
            pass

    # ── 4. Dashboard 自身 ──
    logs.append({"time": now.strftime("%Y-%m-%d %H:%M:%S"), "level": "INFO",
                 "source": "Dashboard", "category": "系统",
                 "message": f"Dashboard 运行中（端口 {ACP_PORT}）"})

    # 知识库文件统计
    kb = WORKSPACE_DIR / "knowledge"
    if kb.exists():
        md_count = sum(1 for _ in kb.rglob("*.md") if "草稿" not in str(_))
        logs.append({"time": now.strftime("%Y-%m-%d %H:%M:%S"), "level": "INFO",
                     "source": "Knowledge", "category": "知识库",
                     "message": f"知识库共 {md_count} 个 Markdown 文件"})

    # Copaw 错误日志（如存在）
    copaw_log = WORKSPACE_DIR / ".qwenpaw" / "logs" / "copaw.log"
    if copaw_log.exists():
        try:
            lines = copaw_log.read_text(encoding="utf-8", errors="replace").split("\n")
            for line in lines[-30:]:
                line = line.strip()
                if not line: continue
                lvl = "ERROR" if ("ERROR" in line or "error" in line or "fail" in line.lower()) else \
                      "WARNING" if ("WARN" in line or "warning" in line) else "INFO"
                logs.append({"time": now.strftime("%Y-%m-%d %H:%M:%S"),
                             "level": lvl, "source": "Copaw", "category": "系统",
                             "message": line[:150]})
        except Exception:
            pass

    # 统一修复乱码
    for entry in logs:
        entry["message"] = fix_garbled_text(entry["message"])

    # 按时间逆序（最新在前）
    logs.sort(key=lambda x: x["time"], reverse=True)
    return logs


# ==================== ROUTES ====================

@app.route('/logs')
def logs_page():
    response = app.make_response(render_template('logs.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store'
    return response


@app.route('/')
def index():
    response = app.make_response(render_template('index.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.after_request
def add_no_cache(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/api/alerts')
def api_alerts():
    """从最近的 memory 日志中提取告警/警告/错误"""
    try:
        memory_dir = WORKSPACE_DIR / "memory"
        alerts = []
        if memory_dir.exists():
            files = sorted(memory_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
            for mf in files[:5]:  # 最近5个日志文件
                try:
                    lines = mf.read_text(encoding="utf-8-sig", errors="replace").split('\n')
                    date_str = mf.stem
                    for i, line in enumerate(lines):
                        lower = line.lower()
                        # 匹配警告/错误/失败关键词
                        if any(kw in lower for kw in ('错误', 'error', '失败', 'fail', '警告', 'warning', '异常', 'exception', '超时', 'timeout', '崩溃', 'crash')):
                            alerts.append({
                                "date": date_str,
                                "line": i + 1,
                                "text": line.strip()[:200],
                                "severity": "error" if any(kw in lower for kw in ('error', '失败', 'fail', 'exception', 'crash', '崩溃')) else "warning"
                            })
                            if len(alerts) >= 20:
                                break
                except Exception:
                    pass
                if len(alerts) >= 20:
                    break
        return jsonify({"alerts": alerts[:20], "total": len(alerts)})
    except Exception as e:
        return jsonify({"error": str(e), "last_update": datetime.now().isoformat()})


def _enrich_agents_health(agents):
    """给 agents 列表添加 health / task_count / load 字段"""
    tasks, _ = parse_tasks_state()
    task_counts = {}
    if tasks:
        for t in tasks:
            ag = t.get("agent", "—")
            if ag and ag != "—":
                task_counts[ag] = task_counts.get(ag, 0) + 1
    coord_dir = WORKSPACE_DIR / "_copaw" / "coordination"
    agent_activity = {}
    if coord_dir.exists():
        for tf in coord_dir.glob("T-*.md"):
            try:
                content = tf.read_text(encoding="utf-8-sig", errors="replace")
                agent_m = re.search(r'(?:Agent|负责人|assignee)[：:]\s*(\S+)', content)
                if agent_m:
                    ag = agent_m.group(1)
                    mtime = os.path.getmtime(str(tf))
                    if ag not in agent_activity or mtime > agent_activity[ag]:
                        agent_activity[ag] = mtime
            except Exception:
                pass
    now = time.time()
    import os  # noqa (already at top)
    for a in agents:
        aname = a["name"]
        a["task_count"] = task_counts.get(aname, 0)
        tc = a["task_count"]
        a["load"] = "high" if tc >= 5 else "medium" if tc >= 2 else "low"
        last = agent_activity.get(aname)
        if last:
            a["last_active"] = time.strftime("%m-%d %H:%M", time.localtime(last))
            a["last_active_ts"] = last
        else:
            a["last_active"] = None
            a["last_active_ts"] = None
        if last and (now - last) < 86400:
            a["health"] = "healthy" if (now - last) < 3600 else "idle"
        else:
            a["health"] = a.get("status", "online")

    # 知识贡献活跃度
    knowledge_counts = compute_agent_knowledge_contributions()
    for a in agents:
        a["knowledge_contributions"] = knowledge_counts.get(a["name"], 0)


@app.route('/api/stats/agent-tasks')
def api_stats_agent_tasks():
    """返回各 Agent 参与的任务数量统计"""
    tasks, _ = parse_tasks_state()
    counts = {}
    if tasks:
        for t in tasks:
            ag = t.get("agent", "—").strip()
            if ag and ag != "—":
                counts[ag] = counts.get(ag, 0) + 1
    # 按数量降序排列
    result = [{"name": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]
    return jsonify({"agent_tasks": result, "total": sum(counts.values())})


@app.route('/api/stats')
def api_stats():
    try:
        agents, _ = fetch_copaw_agents()
        tasks, _ = parse_tasks_state()
        if agents is None:
            agents = []
        if tasks is None:
            tasks = []
        # 给 agents 加健康数据
        _enrich_agents_health(agents)
        stats = compute_stats(agents, tasks)
        stats["knowledge_ratio"] = compute_knowledge_ratio(tasks)
        stats["knowledge_trend"] = compute_knowledge_trend()
        stats["review_severity"] = compute_review_severity()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e), "last_update": datetime.now().isoformat()})


@app.route('/api/agents')
def api_agents():
    agents, err = fetch_copaw_agents()
    if agents is None:
        return jsonify({"agents": [], "error": err})
    _enrich_agents_health(agents)
    return jsonify({"agents": agents, "total": len(agents)})


@app.route('/api/agent/<agent_id>/tasks')
def api_agent_tasks(agent_id):
    """返回某个 agent 的最近任务"""
    tasks, _ = parse_tasks_state()
    if not tasks:
        return jsonify({"tasks": [], "agent_id": agent_id})
    agents, _ = fetch_copaw_agents()
    agent_name = agent_id
    if agents:
        ag = next((a for a in agents if a["id"] == agent_id), None)
        if ag:
            agent_name = ag["name"]
    matched = [t for t in tasks if agent_name in (t.get("agent") or "")]
    matched.sort(key=lambda t: t["id"], reverse=True)
    return jsonify({"tasks": matched[:20], "agent_id": agent_id, "agent_name": agent_name, "total": len(matched)})


@app.route('/api/agent/<agent_id>/soul')
def api_agent_soul(agent_id):
    """读取某个 Agent 的 SOUL.md"""
    # agent_id → workspace 目录映射
    workspace_map = {
        "default": "default",
        "iPt2x8": "rose",
        "cxdNEN": "qiji",
        "mWNCXY": "manong",
        "XuFfNm": "xiaoceng",
        "UKCexb": "xiaoa",
        "Z5edzS": "dazhuojia",
        "jzFWyP": "zongguan",
        "hGmevJ": "zhijianzhe",
    }
    ws = workspace_map.get(agent_id, agent_id)
    ws_dir = WORKSPACE_DIR.parent / ws
    soul_path = ws_dir / "SOUL.md"
    # 尝试编码
    if not soul_path.exists():
        return jsonify({"error": "SOUL.md not found", "path": str(soul_path)}), 404
    try:
        raw_bytes = soul_path.read_bytes()
        # 尝试 UTF-8
        try:
            content = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            content = raw_bytes.decode("utf-8", errors="replace")
        # 检测双重编码污染（UTF-8 → Latin-1 → UTF-8），特征是大量 Â/Ã 开头的"中文"
        # 简单检测：如果前500字符中高字节字符占比异常，尝试恢复
        test = content[:500]
        high_bytes = sum(1 for c in test if ord(c) > 127)
        if high_bytes > len(test) * 0.5:
            # 可能是双重编码：先 encode latin-1，再 decode utf-8
            try:
                recovered = raw_bytes.decode("utf-8-sig").encode("latin-1").decode("utf-8")
                # 验证恢复后是否看起来像正常中文
                test2 = recovered[:200]
                cjk = sum(1 for c in test2 if '\u4e00' <= c <= '\u9fff')
                if cjk > 10:
                    content = recovered
            except Exception:
                pass
        # 过滤 PUA 字符
        import unicodedata
        cleaned = []
        for ch in content:
            cp = ord(ch)
            if 0xE000 <= cp <= 0xF8FF:
                continue
            if unicodedata.category(ch) == 'Co':
                continue
            cleaned.append(ch)
        content = ''.join(cleaned)
        return jsonify({"agent_id": agent_id, "path": str(soul_path), "content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/tasks')
def api_tasks():
    tasks, err = parse_tasks_state()
    if tasks is None:
        return jsonify({"tasks": [], "error": err})
    return jsonify({"tasks": tasks, "total": len(tasks)})


@app.route('/api/task/<task_id>')
def api_task_detail(task_id):
    """读取协调文件；乱码则跳过，统一从 tasks_state 取结构化数据渲染。
    额外返回知识入库状态和关联知识条目。"""
    coord_dir = WORKSPACE_DIR / "_copaw" / "coordination"
    candidates = list(coord_dir.glob(f"{task_id}*.md"))

    content = None
    filename = None
    if candidates:
        raw = candidates[0].read_text(encoding="utf-8-sig", errors="replace")
        pua = bool(re.search(r'[\ue000-\uf8ff]', raw))
        unreadable = len(re.findall(r'[^\x20-\x7e\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\n\r]', raw.replace(' ','').replace('\t','')))
        total = max(len(raw), 1)
        if not pua and unreadable / total < 0.15:
            content = raw
            filename = candidates[0].name

    # 从 tasks_state.md 提取本条结构化信息
    tasks, _ = parse_tasks_state()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    # 从 tasks_state.md 原表提取额外字段（日期、备注）
    extra = {}
    if TASKS_STATE_FILE.exists():
        state_text = TASKS_STATE_FILE.read_text(encoding="utf-8-sig")
        for line in state_text.split('\n'):
            if task_id in line:
                cols = [c.strip() for c in line.split('|') if c.strip()]
                if len(cols) >= 5:
                    extra['date'] = cols[2] if len(cols) > 2 else ''
                    extra['note'] = cols[4] if len(cols) > 4 else ''
                break

    # ==== 知识入库状态检查 + 知识库全文搜索 ====
    knowledge_status = "未入库"
    related_knowledge = []
    knowledge_snippets = []
    task_name = task.get("name", "")

    # 1) 查 03_最新入库.md
    latest_kb = KNOWLEDGE_DIR / "总纲" / "03_最新入库.md"
    if latest_kb.exists():
        kb_text = latest_kb.read_text(encoding="utf-8-sig")
        for line in kb_text.split('\n'):
            if task_id.upper() in line.upper() or (task_name and task_name[:20] in line):
                knowledge_status = "已入库"
                cols = [c.strip() for c in line.split('|') if c.strip()]
                if cols[0] not in ('时间', ':---') and len(cols) >= 2:
                    related_knowledge.append({
                        "date": cols[0] if len(cols) > 0 else "",
                        "name": cols[1].replace("**", "").strip() if len(cols) > 1 else "",
                        "domain": cols[2] if len(cols) > 2 else "",
                        "level": cols[3] if len(cols) > 3 else "",
                    })
                break

    # 2) 全文搜索知识库：找任务相关 snippet
    if KNOWLEDGE_DIR.exists():
        import fnmatch
        keywords = [task_id]
        if task_name:
            name_parts = task_name.replace("：", " ").replace(":", " ").split()
            keywords.extend([p for p in name_parts[:2] if len(p) >= 2])

        for md_file in KNOWLEDGE_DIR.rglob("*.md"):
            if "总纲" in str(md_file):
                continue
            # 多编码尝试
            text = None
            for enc in ('utf-8-sig', 'utf-8', 'gbk', 'gb2312'):
                try:
                    raw = md_file.read_bytes()
                    text = raw.decode(enc)
                    if len(re.findall(r'[\ue000-\uf8ff]', text)) > len(text) * 0.05:
                        continue
                    break
                except: continue
            if not text:
                continue

            for kw in keywords:
                if kw in text and len(kw) >= 3:
                    # 提取摘要：优先总结段落 → 首个实质段落
                    summary = ""
                    # 先找总结性标题
                    summary_headers = ['核心发现', '总结', '关键决策', '经验教训', '关键原则', '结论',
                                       '核心规则', '关键教训', '解决方案', '最佳实践', '关键洞察',
                                       '复盘总结', '升级内容', '改进内容']
                    for section in re.split(r'\n##?\s+', text):
                        sl = section[:40].lower()
                        if any(h in sl for h in summary_headers):
                            # 取该段内容，跳过首行标题
                            lines = section.split('\n')
                            body = '\n'.join(lines[1:]).strip() if len(lines) > 1 else section.strip()
                            # 清理表格行和空行
                            clean = []
                            for l in body.split('\n'):
                                l = l.strip()
                                if l.startswith('|') or l.startswith('>') or len(l) < 10:
                                    continue
                                clean.append(l)
                            if clean:
                                summary = ' '.join(clean)[:180]
                                if len(summary) > 160:
                                    summary = summary[:160] + "…"
                                break
                    # 后备：取首个实质段落
                    if not summary:
                        paras = [p.strip() for p in text.split('\n\n')
                                 if len(p.strip()) > 50 and not p.startswith('#')
                                 and not p.startswith('|') and not p.startswith('>')]
                        if paras:
                            p = paras[0]
                            if '\n' in p:
                                p = ' '.join(p.split('\n'))
                            summary = p[:180] + ("…" if len(p) > 180 else "")
                    if not summary or re.search(r'[\ue000-\uf8ff]', summary):
                        continue
                    rel_path = str(md_file.relative_to(KNOWLEDGE_DIR)).replace('\\', '/')
                    knowledge_snippets.append({
                        "file": rel_path,
                        "url": f"/api/docs/{rel_path}",
                        "snippet": summary,
                        "keyword": kw,
                    })
                    break

        seen = set()
        unique_snippets = []
        for s in knowledge_snippets:
            if s["file"] not in seen:
                seen.add(s["file"])
                unique_snippets.append(s)
        knowledge_snippets = unique_snippets[:8]

    # 构建 Markdown 详情
    status_labels = {"executing": "🔧 执行中", "completed": "✅ 已完成", "cancelled": "❌ 已取消"}
    priority_labels = {"high": "高", "medium": "中", "low": "低"}
    status = status_labels.get(task.get("status", ""), task.get("status", "—"))
    priority = priority_labels.get(task.get("priority", "medium"), "中")

    lines = [
        f"# {task.get('name', task_id)}",
        "",
        "| 属性 | 值 |",
        "|:---|:---|",
        f"| 任务 ID | `{task_id}` |",
        f"| 状态 | {status} |",
        f"| 优先级 | {priority} |",
        f"| 进度 | {task.get('progress', 0)}% |",
    ]
    if task.get("agent") and task["agent"] != "—":
        lines.append(f"| 负责人 | {task['agent']} |")
    if extra.get("date"):
        lines.append(f"| 日期 | {extra['date']} |")
    if extra.get("note"):
        lines.append(f"| 备注 | {extra['note']} |")

    # 知识入库状态行
    kb_icon = "📚" if knowledge_status == "已入库" else "📝"
    lines.append(f"| 知识入库 | {kb_icon} {knowledge_status} |")

    if filename:
        lines.append("")
        lines.append(f"📄 协调文件：`{filename}`")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(content)
    else:
        lines.append("")
        lines.append("> 暂无协调文件（或文件编码损坏）")

    summary = "\n".join(lines)
    return jsonify({
        "task_id": task_id,
        "content": summary,
        "filename": filename,
        "has_coordination": filename is not None,
        "knowledge_status": knowledge_status,
        "related_knowledge": related_knowledge,
        "knowledge_snippets": knowledge_snippets,
    })


@app.route('/api/workflow')
def api_workflow():
    """返回全流程 7 节点状态 + 归档池（7天窗口）"""
    tasks, _ = parse_tasks_state()
    if tasks is None:
        tasks = []

    # 7 活跃节点（归档移出）
    stages = [
        {"id": "receive", "label": "任务接收", "phase": "input"},
        {"id": "assess", "label": "复杂度判定", "phase": "analysis"},
        {"id": "dedup", "label": "知识去重", "phase": "analysis"},
        {"id": "dispatch", "label": "调度下发", "phase": "dispatch"},
        {"id": "execute", "label": "Agent 执行", "phase": "execute"},
        {"id": "feedback", "label": "结果反馈", "phase": "review"},
        {"id": "review", "label": "验收判定", "phase": "review"},
    ]

    # 按状态分类任务
    executing = [t for t in tasks if t.get("status") == "executing"]
    completed = [t for t in tasks if t.get("status") == "completed"]
    pending = [t for t in tasks if t.get("status") in ("pending",)]

    # 7 天窗口：筛选近期完成任务
    now_ts = time.time()
    seven_days_ago = now_ts - 7 * 86400
    completed_7day = []
    for t in completed:
        date_str = t.get("date", "") or t.get("completed", "")
        if date_str:
            try:
                dt = datetime.fromisoformat(date_str[:10]).timestamp()
                if dt >= seven_days_ago:
                    completed_7day.append(t)
            except:
                completed_7day.append(t)  # 解析失败则纳入
        else:
            completed_7day.append(t)

    # 归档池数据
    archive_pool = {
        "count_total": len(completed),
        "count_7day": len(completed_7day),
        "tasks_7day": [{
            "agent": t.get("agent", "—"),
            "task_id": t.get("id", ""),
            "task_name": t.get("name", ""),
            "date": t.get("date", "") or t.get("completed", ""),
        } for t in completed_7day],
    }

    # 聚合输出
    result_stages = []
    for s in stages:
        sid = s["id"]
        item = {"id": sid, "label": s["label"], "phase": s["phase"]}
        if sid == "execute":
            item["count"] = len(executing)
            item["tasks"] = [{
                "agent": t.get("agent", "—"),
                "task_id": t.get("id", ""),
                "task_name": t.get("name", ""),
                "progress": t.get("progress", 50),
                "estimated_minutes": t.get("estimated_minutes"),
                "start_time": t.get("start_time"),
                "current_stage": t.get("current_stage"),
            } for t in executing]
        elif sid == "feedback":
            item["count"] = 0
        elif sid == "review":
            item["count"] = 0
        elif sid == "assess":
            item["count"] = len(pending)
        else:
            item["count"] = 0
        result_stages.append(item)

    # 计算滞留时长（仅活跃阶段，归档不算）
    for s in result_stages:
        if s["id"] == "execute" and executing:
            dwells = []
            for t in executing:
                st = t.get("start_time")
                if st:
                    try:
                        dt = datetime.fromisoformat(st).timestamp()
                        dwells.append(now_ts - dt)
                    except: pass
            s["dwell_seconds"] = sum(dwells) / len(dwells) if dwells else 0
        elif s.get("count", 0) > 0:
            s["dwell_seconds"] = s["count"] * 300
        else:
            s["dwell_seconds"] = 0

    # 确定活跃阶段：优先 execute > assess
    active = "receive"
    if executing:
        active = "execute"
    elif pending:
        active = "assess"
    else:
        for s in reversed(result_stages):
            if s.get("count", 0) > 0:
                active = s["id"]
                break

    return jsonify({
        "stages": result_stages,
        "archive": archive_pool,
        "total": len(tasks),
        "active_stage": active,
        "active_tasks": [{
            "agent": t.get("agent", "—"),
            "task_id": t.get("id", ""),
            "task_name": t.get("name", ""),
            "progress": t.get("progress", 50),
            "estimated_minutes": t.get("estimated_minutes"),
            "start_time": t.get("start_time"),
            "current_stage": t.get("current_stage"),
        } for t in executing],
        "completed_tasks": [{
            "agent": t.get("agent", "—"),
            "task_id": t.get("id", ""),
            "task_name": t.get("name", ""),
        } for t in completed],
    })


LOG_SOURCES = {
    "dashboard": "06_Dashboard",
    "system": "QwenPaw",
    "copaw": ".qwenpaw/logs",
}


def get_real_logs():
    """收集真实日志：Dashboard + 最近的事件"""
    logs = []
    # 1. Dashboard 启动日志
    logs.append({"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "level": "INFO",
                 "source": "Dashboard", "message": "Dashboard 运行中"})
    # 2. 检查 tasks_state 最后修改时间
    if TASKS_STATE_FILE.exists():
        mtime = datetime.fromtimestamp(TASKS_STATE_FILE.stat().st_mtime)
        logs.append({"time": mtime.strftime("%Y-%m-%d %H:%M:%S"), "level": "INFO",
                     "source": "Tasks", "message": f"tasks_state.md 最后更新: {mtime.strftime('%H:%M')}"})
    # 3. 知识库索引更新时间
    idx_file = WORKSPACE_DIR / "knowledge" / "总纲" / "index.md"
    if idx_file.exists():
        mtime = datetime.fromtimestamp(idx_file.stat().st_mtime)
        logs.append({"time": mtime.strftime("%Y-%m-%d %H:%M:%S"), "level": "INFO",
                     "source": "Knowledge", "message": f"知识库总纲最后更新: {mtime.strftime('%H:%M')}"})
    return logs


@app.route('/api/logs')
def api_logs():
    level_filter = request.args.get("level", "all")
    cat_filter = request.args.get("category", "all")
    log_entries = get_recent_logs_from_files()

    if level_filter != "all":
        log_entries = [e for e in log_entries if e["level"].upper() == level_filter.upper()]
    if cat_filter != "all":
        log_entries = [e for e in log_entries if e.get("category", "") == cat_filter]

    return jsonify({"logs": log_entries, "total": len(log_entries)})


@app.route('/api/docs')
def api_docs():
    # 按路径直接读取知识库文件
    req_path = request.args.get("path", "")
    if req_path:
        fp = KNOWLEDGE_DIR / req_path
        if fp.exists() and fp.is_relative_to(KNOWLEDGE_DIR) and fp.suffix == '.md':
            return jsonify({
                "id": req_path,
                "title": fp.stem,
                "path": req_path,
                "content": fp.read_text(encoding="utf-8-sig", errors="replace")
            })
        return jsonify({"error": "File not found"}), 404

    # 按 ID 查找目录条目
    doc_id = request.args.get("id", "")
    if doc_id:
        doc = get_doc_content(doc_id)
        if doc:
            return jsonify(doc)
        return jsonify({"error": "Not found"}), 404

    return jsonify({"docs": get_docs_list(), "total": len(DOCS_CATALOG)})


@app.route('/api/docs/search')
def api_docs_search():
    """全文搜索知识库"""
    q = request.args.get("q", "").strip()
    if len(q) < 1:
        return jsonify({"results": [], "total": 0})
    results = []
    for md_file in KNOWLEDGE_DIR.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8-sig", errors="replace")
            rel = str(md_file.relative_to(KNOWLEDGE_DIR)).replace("\\", "/")
            if q.lower() in content.lower():
                # 提取摘要（搜索词前后各 80 字）
                idx = content.lower().find(q.lower())
                start = max(0, idx - 60)
                end = min(len(content), idx + len(q) + 80)
                snippet = content[start:end].replace('\n', ' ')
                if start > 0:
                    snippet = "…" + snippet
                if end < len(content):
                    snippet += "…"
                results.append({
                    "id": rel,
                    "title": md_file.stem,
                    "path": rel,
                    "snippet": snippet.strip(),
                    "score": content.lower().count(q.lower())
                })
        except Exception:
            continue
    results.sort(key=lambda r: r["score"], reverse=True)
    return jsonify({"results": results[:20], "total": len(results)})


@app.route('/api/docs/tree')
def api_docs_tree():
    """返回知识库完整树形结构"""
    return jsonify(build_knowledge_tree())


@app.route('/api/docs/<path:doc_path>')
def api_doc_content(doc_path):
    """读取知识库文件原始内容"""
    kb = WORKSPACE_DIR / "knowledge"
    fp = kb / doc_path
    if not fp.exists() or not fp.is_relative_to(kb):
        return jsonify({"error": "Not found"}), 404
    content = fp.read_text(encoding="utf-8-sig", errors="replace")
    return jsonify({"path": doc_path, "name": fp.stem, "content": content})


@app.route('/api/agent/<agent_id>')
def api_agent_detail(agent_id):
    agents, _ = fetch_copaw_agents()
    if agents:
        agent = next((a for a in agents if a["id"] == agent_id), None)
        if agent:
            return jsonify(agent)
    return jsonify({"error": "Agent not found"}), 404


# 服务绑定配置（默认仅本机；可用环境变量 ACP_HOST / ACP_PORT / ACP_DEBUG 覆盖）
import os as _os
ACP_HOST = _os.environ.get("ACP_HOST", "127.0.0.1")
ACP_PORT = int(_os.environ.get("ACP_PORT", "8083"))
ACP_DEBUG = _os.environ.get("ACP_DEBUG") == "1"


if __name__ == '__main__':
    print("=" * 50)
    print(f"ACP Dashboard running at http://{ACP_HOST}:{ACP_PORT}")
    print("=" * 50)
    # debug 默认关闭：Werkzeug 调试器可被触发执行任意代码，切勿在对外环境开启
    app.run(host=ACP_HOST, port=ACP_PORT, debug=ACP_DEBUG, use_reloader=False)