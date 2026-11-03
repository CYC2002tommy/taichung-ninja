# -*- coding: utf-8 -*-
"""台中黑哥 (the commander): action-time skill dispatch and the decision gate.

Registered for PreToolUse (Read|Write|Edit|Bash|PowerShell|Skill|mcp__matlab__.*) and Stop in settings.json.
Skill: ~/.claude/skills/commander/SKILL.md. Personal settings: ~/.claude/commander/config.json (see DEFAULT_CONFIG).
Upstream: github.com/CYC2002tommy/taichung-ninja (this file is shared verbatim; keep personal data in the config).

PreToolUse:
  * Skill(X) or Read(.../skills/X/SKILL.md)  -> record X as loaded for this transcript (silent).
  * Action routes (high-precision signatures)  -> additionalContext naming skills to load (soft), except
    three deny-once routes: Read(*.pdf) -> markitdown, and Write of a NEW docx / pptx builder.
    At most 2 skills per call and 6 reminders per transcript; a skill is named at most once.
  * Decision gate (main agent only): if Claude's text since the last user prompt makes a choice on
    the owner's behalf and nothing authorizes it, deny the call once, naming the phrase.
Stop:
  * Same decision gate on last_assistant_message, returned as Stop feedback (additionalContext).

Fail open: any internal error prints nothing and exits 0. Output is ASCII JSON (\\u escapes).
State: %LOCALAPPDATA%\\commander\\state\\<sha1(transcript_path|agent_id)>.json
"""
import hashlib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.environ.get('COMMANDER_LOG') or os.path.join(HERE, 'commander_dispatch.log.jsonl')
STATE_DIR = os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'commander', 'state')

# Personal settings live in a config file, never in this script (it is shared as-is):
#   $COMMANDER_CONFIG, else <this hooks dir>/../commander/config.json. Every key is optional.
DEFAULT_CONFIG = {
    'owner': '使用者',                                  # how messages name the person whose decisions are gated
    'skills_root': os.path.join(os.path.expanduser('~'), '.claude', 'skills'),
    'output_review_skill': 'hermes-research:remi',     # reviewed before any file output; null turns the gate off
    'auth_user_regex': r"你(來|就)?決定|你幫我決定|你自己決定|不用問我|別問我|不要問我|全照建議|照建議|照你的建議|直接做|你看著辦|交給你"
                       r"|\byou decide\b|\bup to you\b|\bdon't ask me\b|\bgo ahead\b",
    'delegated_regex': None,                            # contexts where Claude decides directly (prompt, reply or cwd)
    'delegated_label': 'delegated project',
}


def _load_config():
    cfg = dict(DEFAULT_CONFIG)
    p = os.environ.get('COMMANDER_CONFIG') or os.path.join(os.path.dirname(HERE), 'commander', 'config.json')
    try:
        with open(p, encoding='utf-8') as f:
            cfg.update({k: v for k, v in json.load(f).items() if not k.startswith('_')})
    except (OSError, ValueError):
        pass
    return cfg


CFG = _load_config()
SKILLS = CFG['skills_root']
MAX_PER_CALL = 2
MAX_PER_TRANSCRIPT = 6
TAIL_BYTES = 4 * 1024 * 1024

# ---------------------------------------------------------------- action routes
# (id, how, target, deny_once, predicate) ; how = 'skill' (Skill tool) or 'read' (Read SKILL.md path)
CODE_EXT = ('.py', '.js', '.cjs', '.mjs', '.ts', '.ps1', '.sh', '.m', '.ipynb', '.r', '.jl')


def _k(rel):
    return os.path.join(SKILLS, *rel.split('/'))


ROUTES = [
    # output review gate: deny the first file output of a session until the review skill is loaded
    ('output-review', 'skill', CFG.get('output_review_skill') or '', True, 'file_output'),
    ('markitdown', 'skill', 'markitdown', True, 'pdf_read'),
    ('anthropic-skills:docx', 'skill', 'anthropic-skills:docx', True,
     r"^\s*from docx import|^\s*import docx\b|require\(\s*['\"]docx['\"]\s*\)|^\s*import .* from ['\"]docx['\"]|Word\.Application"),
    ('anthropic-skills:pptx', 'skill', 'anthropic-skills:pptx', True,
     r"require\(\s*['\"]pptxgenjs['\"]\s*\)|^\s*import .* from ['\"]pptxgenjs['\"]|^\s*from pptx import|^\s*import pptx\b|PowerPoint\.Application"),
    ('anthropic-skills:xlsx', 'skill', 'anthropic-skills:xlsx', False, r"\bimport openpyxl|from openpyxl|xlsxwriter|\.to_excel\("),
    ('hermes-research:latex-workflows', 'skill', 'hermes-research:latex-workflows', False, 'tex_file'),
    ('k-dense-science:scikit-learn', 'skill', 'k-dense-science:scikit-learn', False,
     r"from sklearn|import sklearn|import xgboost|from xgboost|XGB(Regressor|Classifier)|import lightgbm|from lightgbm"),
    ('k-dense-science:shap', 'skill', 'k-dense-science:shap', False, r"\bimport shap\b"),
    ('k-dense-science:statistical-analysis', 'skill', 'k-dense-science:statistical-analysis', False,
     r"from scipy import stats|scipy\.stats|\bttest_(ind|rel|1samp)|mannwhitneyu|\bwilcoxon\(|\bkruskal\(|f_oneway|import pingouin"),
    ('k-dense-science:statsmodels', 'skill', 'k-dense-science:statsmodels', False,
     r"import statsmodels|from statsmodels|\bsmf\.(ols|glm|mixedlm|logit)|\bsm\.(OLS|GLM|WLS)\b|import linearmodels|from linearmodels|import binsreg"),
    ('k-dense-science:uncertainty-and-units', 'skill', 'k-dense-science:uncertainty-and-units', False,
     r"from SALib|import SALib|\bfast_sampler\b|\befast\b|import pint\b|import uncertainties"),
    ('k-dense-science:scientific-visualization', 'skill', 'k-dense-science:scientific-visualization', False, 'py_plot'),
    ('hermes-matlab:matlab-development', 'skill', 'hermes-matlab:matlab-development', False, 'matlab_fig'),
    ('k-dense-science:geopandas', 'skill', 'k-dense-science:geopandas', False, r"\bimport geopandas|from geopandas"),
    ('hermes-domain:geospatial-data-processing', 'skill', 'hermes-domain:geospatial-data-processing', False,
     r"\bimport rasterio|from rasterio|\bimport rioxarray|from osgeo import gdal"),
    ('hermes-domain:pytorch-hpc', 'skill', 'hermes-domain:pytorch-hpc', False, r"^\s*import torch\b|^\s*from torch\b"),
    ('k-dense-science:pymoo', 'skill', 'k-dense-science:pymoo', False, r"from pymoo|import pymoo"),
    ('hermes-domain:milp-optimization', 'skill', 'hermes-domain:milp-optimization', False,
     r"\bimport pulp\b|from pulp import|\bimport pyomo|from pyomo|import gurobipy|from ortools"),
    ('k-dense pymc', 'read', _k('k-dense-science/skills/pymc/SKILL.md'), False, r"\bimport pymc\b|import pymc as"),
    ('k-dense polars', 'read', _k('k-dense-science/skills/polars/SKILL.md'), False, r"\bimport polars\b"),
    ('k-dense dask', 'read', _k('k-dense-science/skills/dask/SKILL.md'), False, r"\bimport dask\b|from dask\b"),
    ('k-dense zarr-python', 'read', _k('k-dense-science/skills/zarr-python/SKILL.md'), False, r"\bimport zarr\b"),
    ('k-dense networkx', 'read', _k('k-dense-science/skills/networkx/SKILL.md'), False, r"\bimport networkx\b"),
    ('k-dense sympy', 'read', _k('k-dense-science/skills/sympy/SKILL.md'), False, r"\bimport sympy\b|from sympy import"),
    ('k-dense citation-management', 'read', _k('k-dense-science/skills/citation-management/SKILL.md'), False, 'bib_file'),
    ('stale-derivative-audit', 'skill', 'stale-derivative-audit', False, r"\bgit mv\b|\bRename-Item\b|\bMove-Item\b"),
]
_RX = {r[0]: re.compile(r[4], re.M) for r in ROUTES
       if r[4] not in ('pdf_read', 'tex_file', 'py_plot', 'matlab_fig', 'bib_file', 'file_output')}
OUT_EXT = ('.docx', '.pptx', '.xlsx', '.pdf')
# commands that produce a deliverable file (documents, decks, sheets, PDFs) or deliver one
OUTPUT_CMD_RX = re.compile(
    r"\.save\(\s*(r|f)?['\"][^'\"\n]+\.(docx|pptx|xlsx)['\"]|\.writeFile\(|Packer\.toBuffer|\bSaveAs2?\s*\(|ExportAsFixedFormat|"
    r"\bpandoc\b[^\n]{0,200}\s-o\s+\S+\.(docx|pdf|pptx)|\b(pdflatex|xelatex|lualatex|latexmk)\b|\bdocx2pdf\b|"
    r"\b(cp|Copy-Item|copy|robocopy)\b[^\n]{0,240}[\\/]Downloads\b|\.to_excel\(|"
    r"\bnode\s+\S*(docx|pptx|deck|slides?|report|letter|email|build)\S*\.(c|m)?js\b", re.I)
PLOT_RX = re.compile(r"\bimport matplotlib|\bimport seaborn|\bplt\.savefig\(|\bfig\.savefig\(|\bimport plotly")
MATLAB_FIG_RX = re.compile(r"\bexportgraphics\s*\(|\bsaveas\s*\(|\bprint\s*\(\s*['\"]?-d(png|pdf|tiff|jpeg)|\bexportgraphics\b")


def _texts(tool, inp):
    """(path, code_text) the signatures look at; code only, never file paths in prose."""
    path = str(inp.get('file_path') or inp.get('notebook_path') or '')
    if tool in ('Write',):
        return path, str(inp.get('content') or '')
    if tool == 'Edit':
        return path, str(inp.get('new_string') or '')
    if tool in ('Bash', 'PowerShell'):
        return '', str(inp.get('command') or '')
    if tool.startswith('mcp__matlab__'):
        return str(inp.get('script_path') or inp.get('file_path') or ''), str(inp.get('code') or inp.get('script') or '')
    return path, ''


def classify(tool, inp):
    """Return [(route_id, how, target, deny_once)] that this tool call calls for."""
    out = []
    path, code = _texts(tool, inp)
    low = path.lower().replace('\\', '/')
    is_code_file = low.endswith(CODE_EXT)
    in_skills = '/.claude/skills/' in low or '/.claude/hooks/' in low   # harness edits: never route
    for rid, how, target, deny, pat in ROUTES:
        hit = False
        if pat == 'file_output':
            if not target:
                continue
            hit = (tool in ('Write', 'Edit') and (low.endswith(OUT_EXT) or '/downloads/' in low)) \
                or (tool in ('Bash', 'PowerShell') and bool(OUTPUT_CMD_RX.search(code)))
            if hit:
                out.append((rid, how, target, True))     # always deny-once (until the review skill is loaded)
            continue
        if pat == 'pdf_read':   # own renders in Temp/scratchpad are visual checks, not content reads
            hit = tool == 'Read' and low.endswith('.pdf') and '/appdata/local/temp/' not in low
        elif pat == 'tex_file':
            hit = tool in ('Write', 'Edit') and low.endswith('.tex')
        elif pat == 'bib_file':
            hit = tool in ('Write', 'Edit') and low.endswith('.bib')
        elif pat == 'py_plot':
            hit = tool in ('Write', 'Edit') and low.endswith('.py') and bool(PLOT_RX.search(code))
        elif pat == 'matlab_fig':
            hit = ((tool in ('Write', 'Edit') and low.endswith('.m')) or tool.startswith('mcp__matlab__')) \
                and bool(MATLAB_FIG_RX.search(code))
        elif code and not in_skills:
            if tool in ('Write', 'Edit') and not is_code_file:
                continue          # prose/markdown that merely mentions a library is not an action
            hit = bool(_RX[rid].search(code))
        if hit and not in_skills:
            # deny-once only for creating a NEW builder (docx/pptx) or a pdf read
            d = deny and (pat == 'pdf_read' or (tool == 'Write' and not os.path.exists(path)))
            out.append((rid, how, target, d))
    return out


# ---------------------------------------------------------------- decision gate
DECIDE_RX = re.compile(
    r"我(先)?(採用|用)(了)?(合理|一個)?預設|我(先)?預設(用|為|成|採用|是)?|我(就)?選了|我挑了|我決定(用|改|採用|先|把|不)|"
    r"我(先|就)?(替|幫)你(決定|選|挑)|我先假設|先假設(你|沒有|是|為)|"
    r"\bI (chose|picked|went with|decided to|defaulted to|assumed)\b|\bI'll go with\b|\bdefaulting to\b")
NEG_RX = re.compile(r"(沒有|沒|不會|不|不要|別|未|並未|不替|不幫)\s*$")
QUOTE_OPEN, QUOTE_CLOSE = '「『"“`', '」』"”`'
AUTH_USER_RX = re.compile(CFG['auth_user_regex'], re.I)
DELEGATED_RX = re.compile(CFG['delegated_regex'], re.I) if CFG.get('delegated_regex') else None
OWNER = CFG.get('owner') or '使用者'


def _inside_quotes(text, i):
    depth = 0
    for ch in text[max(0, i - 120):i]:
        if ch in '「『“':
            depth += 1
        elif ch in '」』”':
            depth = max(0, depth - 1)
    # backticks / straight quotes: odd count before the match on the same line means inside
    line = text[text.rfind('\n', 0, i) + 1:i]
    return depth > 0 or line.count('`') % 2 == 1 or line.count('"') % 2 == 1


def detect_decision(text):
    """Return a short snippet if the text makes a choice on the owner's behalf, else None."""
    for m in DECIDE_RX.finditer(text or ''):
        before = text[max(0, m.start() - 6):m.start()]
        if NEG_RX.search(before) or _inside_quotes(text, m.start()):
            continue
        after = text[m.end():m.end() + 60]
        if re.match(r"\s*(什麼|哪|嗎|？|\?)", after):      # a question, not a decision
            continue
        a = max(0, m.start() - 30)
        return re.sub(r'\s+', ' ', text[a:m.end() + 50]).strip()
    return None


def authorized(user_text, context_text, cwd):
    if AUTH_USER_RX.search(user_text or ''):
        return 'user said so in this conversation'
    if DELEGATED_RX and DELEGATED_RX.search((user_text or '') + ' ' + (context_text or '') + ' ' + (cwd or '')):
        return CFG.get('delegated_label') or 'delegated project'
    return None


# ---------------------------------------------------------------- transcript tail
def tail_context(transcript_path):
    """(last typed user text, assistant text since then) from the transcript tail; ('','') on failure."""
    try:
        size = os.path.getsize(transcript_path)
        with open(transcript_path, 'rb') as f:
            f.seek(max(0, size - TAIL_BYTES))
            chunk = f.read().decode('utf-8', 'replace')
    except OSError:
        return '', ''
    lines = chunk.splitlines()[1:] if size > TAIL_BYTES else chunk.splitlines()
    assistant = []
    for line in reversed(lines):
        if '"type"' not in line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get('isSidechain'):
            continue
        t = ev.get('type')
        c = (ev.get('message') or {}).get('content')
        if t == 'assistant' and isinstance(c, list):
            for b in reversed(c):
                if isinstance(b, dict) and b.get('type') == 'text':
                    assistant.append(b.get('text', ''))
        elif t == 'user' and not ev.get('isMeta'):
            if isinstance(c, list):
                if any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in c):
                    continue
                c = ' '.join(b.get('text', '') for b in c if isinstance(b, dict) and b.get('type') == 'text')
            if isinstance(c, str) and c.strip() and not c.lstrip().startswith('<'):
                return c, '\n'.join(reversed(assistant))
    return '', '\n'.join(reversed(assistant))


# ---------------------------------------------------------------- state
def _state_path(data):
    key = (data.get('transcript_path') or data.get('session_id') or 'none') + '|' + str(data.get('agent_id') or '')
    return os.path.join(STATE_DIR, hashlib.sha1(key.encode('utf-8', 'replace')).hexdigest() + '.json')


def load_state(p):
    try:
        with open(p, encoding='utf-8') as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    for k in ('loaded', 'reminded', 'gates'):
        s.setdefault(k, [])
    return s


def save_state(p, s):
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(s, f)
        os.replace(tmp, p)
    except OSError:
        pass


def log(rec):
    try:
        rec['ts'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except OSError:
        pass


def _loaded_id(tool, inp):
    if tool == 'Skill':
        return str(inp.get('skill') or '').strip() or None
    if tool == 'Read':
        p = str(inp.get('file_path') or '').replace('\\', '/')
        m = re.search(r'/\.claude/skills/(.+)/SKILL\.md$', p, re.I)
        if m:
            rel = m.group(1)
            return 'k-dense ' + rel.split('/')[-1] if rel.startswith('k-dense-science/skills/') else rel.split('/')[-1]
    return None


def _same(a, b):
    return a == b or a.split(':')[-1] == b.split(':')[-1]


# ---------------------------------------------------------------- handlers
def pre_tool(data):
    tool = data.get('tool_name') or ''
    inp = data.get('tool_input') or {}
    sp = _state_path(data)
    st = load_state(sp)
    lid = _loaded_id(tool, inp)
    if lid:
        if lid not in st['loaded']:
            st['loaded'].append(lid)
            save_state(sp, st)
        return None

    # decision gate first (main agent only; tools that change things)
    if not data.get('agent_id') and (tool in ('Write', 'Edit', 'Bash', 'PowerShell') or tool.startswith('mcp__matlab__')):
        user, said = tail_context(data.get('transcript_path') or '')
        snip = detect_decision(said)
        if snip:
            why = authorized(user, said, data.get('cwd'))
            h = hashlib.sha1(snip.encode('utf-8', 'replace')).hexdigest()[:12]
            if not why and h not in st['gates']:
                st['gates'].append(h)
                save_state(sp, st)
                log({'event': 'gate', 'tool': tool, 'snippet': snip})
                return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                        'permissionDecisionReason':
                        '黑哥攔下：你剛才在替 ' + OWNER + ' 做決定 →「' + snip + '」。'
                        '若這屬於已授權範圍（commander 設定或 LOCAL.md 裡的授權專案、' + OWNER + ' 本對話說過「你決定／照建議」、'
                        '專案記憶裡的授權、或黑哥自己的派工與代理數），用一行說明授權依據後重試同一個呼叫（會放行）。'
                        '否則先停下，用 Skill 工具呼叫 grilling，針對這個決定問 ' + OWNER + '；grill 結束後照 commander 技能接 to-spec。'}}

    hits = [r for r in classify(tool, inp)
            if not any(_same(r[0], x) or _same(r[2], x) for x in st['loaded']) and r[0] not in st['reminded']]
    if not hits or len(st['reminded']) >= MAX_PER_TRANSCRIPT:
        return None
    hits = hits[:MAX_PER_CALL]
    deny = [r for r in hits if r[3]]
    for r in hits:
        st['reminded'].append(r[0])
    save_state(sp, st)
    parts = []
    for rid, how, target, _ in hits:
        parts.append('`' + target + '`（Skill 工具）' if how == 'skill' else 'Read `' + target + '`')
    msg = '黑哥派工：這個動作要帶上 ' + '、'.join(parts) + '。還沒載入就先載入再做；只是一行探查可略過。'
    review = next((r for r in hits if r[0] == 'output-review'), None)
    if review:
        msg = ('黑哥攔下：檔案輸出前要先審內容。用 Skill 工具載入 `' + review[2] + '`，'
               '審這份輸出的內容、修掉問題後再輸出；這是草稿或暫存檔就說明後重試。') + ('' if len(hits) == 1 else ' 另外：' + msg)
    log({'event': 'deny' if deny else 'remind', 'tool': tool, 'routes': [r[0] for r in hits]})
    if deny:
        return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                'permissionDecisionReason': msg + '（這次先擋一次；載入後重試會直接放行。）'}}
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'additionalContext': msg}}


def stop(data):
    if data.get('stop_hook_active') or data.get('agent_id'):
        return None
    text = data.get('last_assistant_message') or ''
    snip = detect_decision(text)
    if not snip:
        return None
    user, _ = tail_context(data.get('transcript_path') or '')
    if authorized(user, text, data.get('cwd')):
        return None
    sp = _state_path(data)
    st = load_state(sp)
    h = hashlib.sha1(snip.encode('utf-8', 'replace')).hexdigest()[:12]
    if h in st['gates']:
        return None
    st['gates'].append(h)
    save_state(sp, st)
    log({'event': 'stop_gate', 'snippet': snip})
    return {'hookSpecificOutput': {'hookEventName': 'Stop', 'additionalContext':
            '黑哥攔下：這則回覆替 ' + OWNER + ' 做了決定 →「' + snip + '」。若屬已授權範圍（commander 設定的授權專案、本對話說過「你決定／照建議」、'
            '專案記憶授權、黑哥的派工與代理數），用一行說明依據即可結束；否則用 Skill 工具呼叫 grilling 針對這個決定問 ' + OWNER + '。'}}


def main():
    try:
        raw = sys.stdin.buffer.read()
        data = json.loads(raw.decode('utf-8', 'replace') or '{}')
        ev = data.get('hook_event_name')
        out = pre_tool(data) if ev == 'PreToolUse' else stop(data) if ev == 'Stop' else None
        if out:
            sys.stdout.write(json.dumps(out))      # ASCII (\u escapes): safe under any Windows code page
    except Exception:                              # fail open
        pass
    sys.exit(0)


if __name__ == '__main__':
    main()
