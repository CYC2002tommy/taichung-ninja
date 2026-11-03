# -*- coding: utf-8 -*-
"""Replay commander_dispatch over past tool calls (both accounts) with per-transcript state, as the live hook would.

Reports how many calls would get a soft reminder or a deny-once, per route, with samples, plus how often the
decision gate would fire on past assistant text. Usage: python replay_commander_dispatch.py [YYYY-MM-DD] [samples]
"""
import collections, glob, json, os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import commander_dispatch as cd  # noqa: E402

since = sys.argv[1] if len(sys.argv) > 1 else '2026-08-01'
k = int(sys.argv[2]) if len(sys.argv) > 2 else 3
paths = (glob.glob(os.path.expanduser(r'~/.claude/projects/*/*.jsonl'))
         + glob.glob(os.path.expanduser(r'~/.claude-study/projects/*/*.jsonl')))
n_calls = n_remind = n_deny = n_gate = n_text = 0
per = collections.Counter(); ex = collections.defaultdict(list); gate_ex = []
for p in paths:
    loaded, reminded, last_user = set(), [], ''
    with open(p, encoding='utf-8', errors='replace') as f:
        for line in f:
            if '"type"' not in line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if str(ev.get('timestamp', '')) < since or ev.get('isSidechain'):
                continue
            c = (ev.get('message') or {}).get('content')
            if ev.get('type') == 'user' and not ev.get('isMeta'):
                if isinstance(c, str) and c.strip() and not c.lstrip().startswith('<'):
                    last_user = c
                continue
            if ev.get('type') != 'assistant' or not isinstance(c, list):
                continue
            for b in c:
                if not isinstance(b, dict):
                    continue
                if b.get('type') == 'text':
                    n_text += 1
                    s = cd.detect_decision(b.get('text', ''))
                    if s and not cd.authorized(last_user, b.get('text', ''), ''):
                        n_gate += 1
                        if len(gate_ex) < 12:
                            gate_ex.append(s)
                    continue
                if b.get('type') != 'tool_use':
                    continue
                tool, inp = b.get('name', ''), b.get('input') or {}
                if not (tool in ('Read', 'Write', 'Edit', 'Bash', 'PowerShell', 'Skill') or tool.startswith('mcp__matlab__')):
                    continue
                n_calls += 1
                lid = cd._loaded_id(tool, inp)
                if lid:
                    loaded.add(lid); continue
                hits = [r for r in cd.classify(tool, inp)
                        if not any(cd._same(r[0], x) or cd._same(r[2], x) for x in loaded) and r[0] not in reminded]
                if not hits or len(reminded) >= cd.MAX_PER_TRANSCRIPT:
                    continue
                hits = hits[:cd.MAX_PER_CALL]
                reminded += [r[0] for r in hits]
                deny = any(r[3] for r in hits)
                n_deny += deny; n_remind += not deny
                for r in hits:
                    per[(r[0], 'deny' if r[3] else 'soft')] += 1
                    if len(ex[r[0]]) < k:
                        what = inp.get('file_path') or inp.get('command') or inp.get('code') or ''
                        ex[r[0]].append(f'{tool} ' + str(what).replace('\n', ' ')[:100])
print(f'tool calls {n_calls}; soft reminders {n_remind} ({100*n_remind/max(1,n_calls):.2f}%); '
      f'deny-once {n_deny} ({100*n_deny/max(1,n_calls):.2f}%); transcripts {len(paths)}')
for (rid, kind), n in per.most_common():
    print(f'  {n:5d} {kind:4s} {rid}')
    for x in ex[rid]:
        print('            ', x)
print(f'\ndecision gate: {n_gate} of {n_text} assistant text blocks ({100*n_gate/max(1,n_text):.2f}%)')
for s in gate_ex:
    print('   -', s[:140])
