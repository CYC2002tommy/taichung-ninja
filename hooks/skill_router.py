# -*- coding: utf-8 -*-
r"""Hook (UserPromptSubmit): name the skills whose trigger words appear in the prompt, so Claude loads them first.

Why: skills chosen by description alone get missed; the user wants the ones matching their habits
to trigger automatically. Claude Code has no "force this skill" switch, so a keyword route beside the prompt is
the strongest lever short of a blocking gate.

Routes live in skill_routes.json beside this file (order = priority, at most max_hits per prompt). Prompts that
start with "/" are skipped: the user already named the skill. <pasted_content> blocks and forked-session preambles are
not matched (agy challenger skill-router-20261102 Q2: they fired 22-25 KB skills on boilerplate). Matches are logged to skill_router.log.jsonl (route ids,
matched words, first 80 chars of the prompt) for the harness audit. Output is ASCII JSON. Any error prints
nothing and exits 0.
"""
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROUTES = os.path.join(HERE, 'skill_routes.json')
LOG = os.path.join(HERE, 'skill_router.log.jsonl')


FLAGS = re.I | re.ASCII   # Unicode \b treats CJK as word chars, so 用MODIS would never match \bMODIS\b
PASTED = re.compile(r'<pasted_content\b.*?</pasted_content>', re.S)
FORK_PREAMBLE = re.compile(r'^\s*(?:Background|Task) \(from the session that started this one\):.*?(?:\n\s*\n|\Z)', re.S)


def load_routes(path=ROUTES):
    cfg = json.load(open(path, encoding='utf-8'))
    routes = []
    for r in cfg['routes']:
        routes.append({**r,
                       'any_re': [re.compile(p, FLAGS) for p in r['any']],
                       'not_re': [re.compile(p, FLAGS) for p in r.get('not', [])]})
    return routes, int(cfg.get('max_hits', 3))


def own_words(prompt):
    """The part of the prompt the user typed: pasted blocks and forked-session preambles removed."""
    return FORK_PREAMBLE.sub('', PASTED.sub(' ', prompt))


def match(prompt, routes, max_hits):
    """Return [(route, matched_text)] in priority order, at most max_hits."""
    hits = []
    if not prompt or prompt.lstrip().startswith('/'):
        return hits
    prompt = own_words(prompt)
    for r in routes:
        if any(n.search(prompt) for n in r['not_re']):
            continue
        for p in r['any_re']:
            m = p.search(prompt)
            if m:
                hits.append((r, m.group(0)))
                break
        if len(hits) >= max_hits:
            break
    return hits


DEFAULT_COMMANDER = ('黑哥在場（commander）：回覆第一行寫黑哥一句（黑哥派工／黑哥：這題我自己顧／黑哥算過／黑哥攔下）。'
                     '規則在 ~/.claude/skills/commander/SKILL.md 與同目錄 LOCAL.md；本 session 還沒讀、或剛壓縮過就先 Read。'
                     '檔案輸出前先審內容；要替使用者做未授權的決定→grilling。')


def commander_line():
    """The always-on 黑哥 line; personal standing rules come from the commander config (router_line)."""
    p = os.environ.get('COMMANDER_CONFIG') or os.path.join(os.path.dirname(HERE), 'commander', 'config.json')
    try:
        return json.load(open(p, encoding='utf-8')).get('router_line') or DEFAULT_COMMANDER
    except (OSError, ValueError):
        return DEFAULT_COMMANDER


def message(hits):
    lines = [commander_line()]
    if not hits:
        return lines[0]
    lines.append('技能路由（關鍵字命中）：')
    for r, word in hits:
        line = f'- `{r["skill"]}`（命中「{word}」）'
        if r.get('note'):
            line += '：' + r['note']
        lines.append(line)
    lines.append('任務確實落在該範圍、且本對話還沒載入時，動手前先用 Skill 工具載入；'
                 '只是字面巧合就略過，不必向使用者說明。')
    return '\n'.join(lines)


def main():
    ev = json.loads(sys.stdin.buffer.read().decode('utf-8', 'replace') or '{}')
    if ev.get('hook_event_name') != 'UserPromptSubmit':
        return
    prompt = str(ev.get('prompt') or '')
    try:
        routes, max_hits = load_routes()
        hits = match(prompt, routes, max_hits)
    except Exception:  # noqa: BLE001 - a broken routes file still leaves 黑哥 on duty
        hits = []
    if not prompt.strip():
        return
    if not hits:   # 黑哥 is on duty every prompt (always visible, by design)
        sys.stdout.write(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit',
                                                            'additionalContext': message(hits)}}))
        return
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'ts': datetime.datetime.now().isoformat(timespec='seconds'),
                                'session_id': ev.get('session_id'),
                                'hits': [[r['id'], w] for r, w in hits],
                                'prompt80': prompt[:80]}, ensure_ascii=False) + '\n')
    except OSError:
        pass
    sys.stdout.write(json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit',
                                                        'additionalContext': message(hits)}}))


if __name__ == '__main__':
    try:
        main()
    except Exception:  # noqa: BLE001 - a hook bug must never block or derail the session
        pass
    sys.exit(0)
