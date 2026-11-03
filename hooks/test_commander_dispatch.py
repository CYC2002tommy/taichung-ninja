# -*- coding: utf-8 -*-
"""Tests for commander_dispatch.py (台中黑哥). Run: python test_commander_dispatch.py"""
import json, os, re, subprocess, sys, tempfile
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# a self-contained test config, so the suite runs the same on any machine (shared upstream: taichung-ninja)
_cfg_dir = tempfile.mkdtemp()
TEST_CFG = os.path.join(_cfg_dir, 'config.json')
json.dump({'owner': 'TestOwner', 'output_review_skill': 'hermes-research:remi',
           'skills_root': os.path.join(os.path.dirname(HERE), 'skills'),
           'delegated_regex': 'GrantX|專案甲', 'delegated_label': 'test delegation'},
          open(TEST_CFG, 'w', encoding='utf-8'), ensure_ascii=False)
os.environ['COMMANDER_CONFIG'] = TEST_CFG
import commander_dispatch as cd  # noqa: E402

fails = 0


def check(label, ok):
    global fails
    fails += not ok
    print(('PASS  ' if ok else 'FAIL  ') + label)


def ids(tool, inp):
    return sorted(r[0] for r in cd.classify(tool, inp))


# ---- every routed skill / path exists (challenger Q2); only meaningful where the skills are installed
skills_root = cd.SKILLS
INSTALLED = os.path.isfile(os.path.join(skills_root, 'commander', 'SKILL.md'))
def skill_exists(sid):
    if os.path.isabs(sid):
        return os.path.isfile(sid)
    plug, _, name = sid.rpartition(':')
    cands = [os.path.join(skills_root, name, 'SKILL.md')]
    if plug:
        cands += [os.path.join(skills_root, plug, 'skills', name, 'SKILL.md')]
    if plug in ('anthropic-skills',) or sid in ('code-review',):
        return True     # bundled by the app, not on disk
    return any(os.path.isfile(c) for c in cands)
# Missing skills are a WARNING by default (another person's machine has another skill set; a named skill that is
# not installed simply does nothing). COMMANDER_STRICT=1 turns them into failures (the author's own machine).
STRICT = os.environ.get('COMMANDER_STRICT') == '1'


def need(label, items):
    if not items:
        check(label, True)
    elif STRICT:
        check(label + ' ' + str(items), False)
    else:
        print('WARN  ' + label + ' — not installed here (ignored): ' + ', '.join(items))


missing = [r[2] for r in cd.ROUTES if r[2] and not skill_exists(r[2])] if INSTALLED else []
need('every action route target exists on disk', missing)
sk = open(os.path.join(skills_root, 'commander', 'SKILL.md'), encoding='utf-8').read() if INSTALLED else ''
cited = set(re.findall(r'`((?:k-dense-science|hermes-[a-z]+|anthropic-skills):[a-z0-9-]+|[a-z][a-z0-9-]+(?:-[a-z0-9]+)*)`', sk))
known_plain = {'grilling', 'code-review', 'tdd', 'markitdown',
               'stale-derivative-audit', 'windows-scripting-discipline', 'diagnosing-bugs', 'karpathy-guidelines',
               'harness-evolution-audit', 'setup-matt-pocock-skills', 'grill-me'}
# personal skill names (personas, courses) come from the owner's real config, key known_skills
_own_cfg = os.path.join(os.path.dirname(HERE), 'commander', 'config.json')
if os.path.isfile(_own_cfg):
    known_plain |= set(json.load(open(_own_cfg, encoding='utf-8')).get('known_skills') or [])
bad = sorted(c for c in cited if (':' in c or c in known_plain) and not skill_exists(c) and not c.startswith('anthropic-skills'))
need('every skill ID named in commander/SKILL.md exists', bad)
absent = []
for rel in re.findall(r'Read `([^`]+SKILL\.md)`', sk):
    m = re.search(r'\{([^}]+)\}', rel)
    for alt in (m.group(1).split(',') if m else [None]):
        r2 = rel.replace(m.group(0), alt) if m else rel
        if not os.path.isfile(os.path.join(skills_root, *r2.replace('.../', 'k-dense-science/skills/').split('/'))):
            absent.append(r2)
need('every Read path named in commander/SKILL.md exists', absent)

# ---- action routes: positives
check('Read pdf -> markitdown deny-once', [r for r in cd.classify('Read', {'file_path': r'D:\x\paper.pdf'}) if r[0] == 'markitdown' and r[3]] != [])
newjs = os.path.join(tempfile.gettempdir(), 'nonexistent_builder_8731.js')
check('new docx builder -> docx deny-once', [r for r in cd.classify('Write', {'file_path': newjs, 'content': "const d = require('docx');"}) if r[3]] != [])
check('Edit existing docx builder -> soft', [r for r in cd.classify('Edit', {'file_path': __file__.replace('.py', '.js'), 'new_string': "from docx import Document"}) if r[3]] == [])
check('pptxgenjs -> pptx', 'anthropic-skills:pptx' in ids('Write', {'file_path': r'D:\a\deck.js', 'content': "const p = require('pptxgenjs')"}))
check('sklearn py -> scikit-learn', 'k-dense-science:scikit-learn' in ids('Write', {'file_path': r'D:\a\m.py', 'content': 'from sklearn.model_selection import GroupKFold\nimport xgboost as xgb'}))
check('shap py', 'k-dense-science:shap' in ids('Edit', {'file_path': r'D:\a\m.py', 'new_string': 'import shap'}))
check('scipy.stats in bash heredoc', 'k-dense-science:statistical-analysis' in ids('Bash', {'command': "python - <<'EOF'\nfrom scipy import stats\nEOF"}))
check('statsmodels', 'k-dense-science:statsmodels' in ids('Write', {'file_path': r'D:\a\r.py', 'content': 'import statsmodels.formula.api as smf\nsmf.ols("y~x", d)'}))
check('SALib -> uncertainty', 'k-dense-science:uncertainty-and-units' in ids('Write', {'file_path': r'D:\a\s.py', 'content': 'from SALib.sample import fast_sampler'}))
check('py savefig -> viz', 'k-dense-science:scientific-visualization' in ids('Write', {'file_path': r'D:\a\f.py', 'content': 'import matplotlib.pyplot as plt\nplt.savefig("a.png")'}))
check('.m exportgraphics -> matlab', 'hermes-matlab:matlab-development' in ids('Edit', {'file_path': r'D:\a\f.m', 'new_string': 'exportgraphics(gcf, "a.png", "Resolution", 300)'}))
check('mcp matlab exportgraphics', 'hermes-matlab:matlab-development' in ids('mcp__matlab__evaluate_matlab_code', {'code': 'exportgraphics(gcf,"x.png")'}))
check('.tex -> latex', 'hermes-research:latex-workflows' in ids('Edit', {'file_path': r'D:\w\main.tex', 'new_string': '\\section{A}'}))
check('pymc -> read path', 'k-dense pymc' in ids('Write', {'file_path': r'D:\a\b.py', 'content': 'import pymc as pm'}))
check('git mv -> stale audit', 'stale-derivative-audit' in ids('Bash', {'command': 'git mv a.md b.md'}))
check('rasterio -> geospatial', 'hermes-domain:geospatial-data-processing' in ids('Write', {'file_path': r'D:\a\g.py', 'content': 'import rasterio'}))
check('docx save -> remi gate', any(r[0] == 'output-review' and r[3] for r in cd.classify('Bash', {'command': "python build.py && python -c \"d.save('report.docx')\""})))
check('copy to Downloads -> remi gate', any(r[0] == 'output-review' for r in cd.classify('PowerShell', {'command': r"Copy-Item D:\a\x.pdf C:\Users\someone\Downloads\ "})))
check('pdflatex -> remi gate', any(r[0] == 'output-review' for r in cd.classify('Bash', {'command': 'cd d && pdflatex main.tex'})))
check('node build_docx.js -> remi gate', any(r[0] == 'output-review' for r in cd.classify('Bash', {'command': 'node make_email_docx.js'})))
check('plain python run is not an output', not any(r[0] == 'output-review' for r in cd.classify('Bash', {'command': 'python 22_di_error.py --seed 3'})))
check('Read of own render in Temp is not routed', ids('Read', {'file_path': r'C:\Users\someone\AppData\Local\Temp\claude\x\scratchpad\render.pdf'}) == [])
check('pptxgenjs mentioned in a string is not a builder', ids('Write', {'file_path': r'D:\a\notes.py', 'content': "NEW = {'x': '31 頁 pptxgenjs 交付檔'}"}) == [])
check('python-docx in pip install is not a builder', 'anthropic-skills:docx' not in ids('Bash', {'command': 'pip install python-docx'}))
# ---- negatives
check('markdown note mentioning sklearn is not routed', ids('Write', {'file_path': r'C:\v\note.md', 'content': 'we used from sklearn import x'}) == [])
check('editing a hook file is not routed', ids('Edit', {'file_path': r'C:\Users\someone\.claude\hooks\x.py', 'new_string': 'import matplotlib'}) == [])
check('plain ls is not routed', ids('Bash', {'command': 'ls -la D:/projects'}) == [])
check('Read of a .py is not routed', ids('Read', {'file_path': r'D:\a\m.py'}) == [])
check('vault path alone is not routed', ids('Bash', {'command': 'tail -c 100 "/c/Users/User/Documents/Obsidian Vault/Hermes/Project_Activity_Log.md"'}) == [])

# ---- decision detection
pos = ['有一點我先採用合理預設，你可以推翻：RECO 主線也跟著改成 DT。', '我預設 0.2 並在 CSV 保留門檻欄位',
       '我選了隱私優先', '有一個判斷我先替你決定並寫在計畫裡', '我先假設沒有上限，但新增的會控制在 10 篇左右',
       'I went with the GroupKFold split.', '我決定用複製而非 junction']
neg = ['我沒有替你選答案，只把證據和出處並排。', '我不會替你決定 ε_max 要不要動。', '要刪哪一段我不替你決定',
       '偵測說法：「我先採用預設」「我選了」', '黑哥攔下：「我預設 0.2」要先問你', '以後讀 PDF 我會預設用 markitdown',
       '你要我預設用哪個？', '`我選了` 這類說法']
for s in pos:
    check('decision: ' + s[:24], cd.detect_decision(s) is not None)
for s in neg:
    check('not a decision: ' + s[:24], cd.detect_decision(s) is None)
check('auth: 你決定', cd.authorized('這個你決定就好', '', '') is not None)
check('auth: delegated project cwd', cd.authorized('', '', r'D:\projects\GrantX_flux') is not None)
check('no auth for plain prompt', cd.authorized('把圖重畫', '我預設 0.2', r'D:\projects\other') is None)

# ---- end-to-end through the real script (state in a temp dir)
tmp = tempfile.mkdtemp()
env = dict(os.environ, LOCALAPPDATA=tmp, COMMANDER_LOG=os.path.join(tmp, 'log.jsonl'))
tp = os.path.join(tmp, 't.jsonl')
with open(tp, 'w', encoding='utf-8') as f:
    f.write(json.dumps({'type': 'user', 'message': {'content': '把 NPP 圖十二重畫'}}, ensure_ascii=False) + '\n')
    f.write(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': '門檻我預設 0.2，接著重畫。'}]}}, ensure_ascii=False) + '\n')


def run(payload):
    p = subprocess.run([sys.executable, '-I', os.path.join(HERE, 'commander_dispatch.py')], input=json.dumps(payload).encode(),
                       capture_output=True, env=env, timeout=30)
    return p.returncode, p.stdout.decode('utf-8', 'replace')


base = {'hook_event_name': 'PreToolUse', 'transcript_path': tp, 'cwd': r'D:\projects\other'}
rc, out = run(dict(base, tool_name='Bash', tool_input={'command': 'ls'}))
check('gate denies an unauthorized decision once', rc == 0 and '"deny"' in out and 'grilling' in json.loads(out)['hookSpecificOutput']['permissionDecisionReason'])
rc, out = run(dict(base, tool_name='Bash', tool_input={'command': 'ls'}))
check('same decision passes on retry', rc == 0 and out == '')
rc, out = run(dict(base, tool_name='Read', tool_input={'file_path': r'D:\x\a.pdf'}))
check('pdf read denied once', '"deny"' in out and 'markitdown' in out)
rc, out = run(dict(base, tool_name='Read', tool_input={'file_path': r'D:\x\a.pdf'}))
check('pdf read passes after the reminder', out == '')
rc, out = run(dict(base, tool_name='Skill', tool_input={'skill': 'k-dense-science:scikit-learn'}))
rc, out = run(dict(base, tool_name='Write', tool_input={'file_path': r'D:\a\m.py', 'content': 'import xgboost'}))
check('skill already loaded -> no reminder', out == '')
rc, out = run(dict(base, tool_name='Write', tool_input={'file_path': r'D:\a\m.py', 'content': 'import shap'}))
check('soft reminder is additionalContext, not deny', 'additionalContext' in out and '"deny"' not in out)
rc, out = run({'hook_event_name': 'Stop', 'transcript_path': tp, 'cwd': r'D:\projects\other', 'stop_hook_active': False,
               'last_assistant_message': '完成。我選了 GroupKFold。'})
check('stop gate feedback', 'additionalContext' in out and 'grilling' in out)
rc, out = run({'hook_event_name': 'Stop', 'transcript_path': tp, 'stop_hook_active': True, 'last_assistant_message': '我選了 B'})
check('stop_hook_active -> silent', out == '')
rc, out = run({'hook_event_name': 'PreToolUse', 'agent_id': 'a1', 'transcript_path': tp, 'tool_name': 'Bash', 'tool_input': {'command': 'ls'}})
check('subagent: no decision gate', out == '')
p = subprocess.run([sys.executable, '-I', os.path.join(HERE, 'commander_dispatch.py')], input=b'\xff\xfe junk', capture_output=True, env=env)
check('garbage stdin fails open', p.returncode == 0 and p.stdout == b'')
check('output is ASCII', all(ord(c) < 128 for c in out))

# ---- both accounts register the same commander hooks and budget (challenger simplification)
def hooks_of(path):
    d = json.load(open(path, encoding='utf-8'))
    regs = sorted((ev, m.get('matcher', ''), h.get('command', '')) for ev, arr in d.get('hooks', {}).items()
                  for m in arr for h in m.get('hooks', []) if 'commander' in h.get('command', '') or 'skill_router' in h.get('command', ''))
    return regs, (d.get('env') or {}).get('SLASH_COMMAND_TOOL_CHAR_BUDGET')
MAIN_S, STUDY_S = os.path.expanduser(r'~/.claude/settings.json'), os.path.expanduser(r'~/.claude-study/settings.json')
if os.path.isfile(MAIN_S) and os.path.isfile(STUDY_S):   # a two-account machine; single-account installs skip this
    main_h, study_h = hooks_of(MAIN_S), hooks_of(STUDY_S)
    check('both accounts: identical commander/router hooks + budget', main_h == study_h and len(main_h[0]) >= 3 and main_h[1])
# the shared hook must not carry personal data (it is published verbatim)
src = open(os.path.join(HERE, 'commander_dispatch.py'), encoding='utf-8').read()
# private terms come from the owner's real config (key private_terms), so this file names none of them
_real = os.path.join(os.path.dirname(HERE), 'commander', 'config.json')
_terms = (json.load(open(_real, encoding='utf-8')).get('private_terms') or []) if os.path.isfile(_real) else []
_hits = [t for t in _terms for f in ('commander_dispatch.py', 'skill_router.py', 'test_commander_dispatch.py')
         if re.search(t, open(os.path.join(HERE, f), encoding='utf-8').read())]
check('shared hook files carry none of the private terms ' + str(_hits), not _hits)

print(f'\n{fails} failure(s)')
sys.exit(1 if fails else 0)
