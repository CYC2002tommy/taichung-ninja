# -*- coding: utf-8 -*-
"""Install 台中黑哥 (Taichung Ninja) into a Claude Code config directory.

    python install.py                      # installs into ~/.claude
    python install.py --claude-dir PATH    # another account / instance
    python install.py --dry-run            # show what would change

Copies the skill and hooks, creates the personal files only if they are missing (config.json, LOCAL.md,
skill_routes.json), backs up settings.json, then registers the hooks and the skill-listing budget.
Restart Claude Code (fully) afterwards. Standard library only.
"""
import argparse
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STAMP = time.strftime('%Y%m%d-%H%M%S')
BLOCK_START = '<!-- taichung-ninja:start -->'
CLAUDE_MD_BLOCK = BLOCK_START + '''
## Commander 台中黑哥 (always on)

黑哥 is on duty in every turn. Open every reply with his one line: `黑哥派工：…`, `黑哥：這題我自己顧`,
`黑哥算過：…` or `黑哥攔下：…`. Read `skills/commander/SKILL.md` and `LOCAL.md` (in this Claude folder) once per
session, and again after a compaction. Standing dispatch rules live in `LOCAL.md`.
<!-- taichung-ninja:end -->
'''


def log(msg):
    print(msg)


def copy(src, dst, dry, overwrite=True):
    if os.path.exists(dst) and not overwrite:
        log(f'  keep      {dst} (already exists)')
        return
    if os.path.exists(dst):
        log(f'  backup    {dst}.bak-{STAMP}')
        if not dry:
            shutil.copy2(dst, f'{dst}.bak-{STAMP}')
    log(f'  copy      {dst}')
    if not dry:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)


def add_hook(hooks, event, matcher, command):
    arr = hooks.setdefault(event, [])
    for m in arr:
        if any(h.get('command') == command for h in m.get('hooks', [])):
            return False
    entry = {'hooks': [{'type': 'command', 'command': command}]}
    if matcher:
        entry = {'matcher': matcher, **entry}
    arr.append(entry)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--claude-dir', default=os.path.join(os.path.expanduser('~'), '.claude'))
    ap.add_argument('--python', default=sys.executable, help='interpreter the hooks run with')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--no-claude-md', action='store_true', help='do not append the 台中黑哥 block to CLAUDE.md')
    a = ap.parse_args()
    cd, dry = os.path.abspath(a.claude_dir), a.dry_run
    log(f'Installing 台中黑哥 into {cd}' + ('  (dry run)' if dry else ''))

    copy(os.path.join(HERE, 'skills', 'commander', 'SKILL.md'), os.path.join(cd, 'skills', 'commander', 'SKILL.md'), dry)
    copy(os.path.join(HERE, 'skills', 'commander', 'LOCAL.example.md'), os.path.join(cd, 'skills', 'commander', 'LOCAL.md'), dry, overwrite=False)
    for f in ('commander_dispatch.py', 'skill_router.py', 'test_commander_dispatch.py', 'replay_commander_dispatch.py'):
        copy(os.path.join(HERE, 'hooks', f), os.path.join(cd, 'hooks', f), dry)
    copy(os.path.join(HERE, 'hooks', 'skill_routes.example.json'), os.path.join(cd, 'hooks', 'skill_routes.json'), dry, overwrite=False)
    cfg_dst = os.path.join(cd, 'commander', 'config.json')
    if not os.path.exists(cfg_dst):
        cfg = json.load(open(os.path.join(HERE, 'config.example.json'), encoding='utf-8'))
        cfg['skills_root'] = os.path.join(cd, 'skills')
        log(f'  create    {cfg_dst}')
        if not dry:
            os.makedirs(os.path.dirname(cfg_dst), exist_ok=True)
            json.dump(cfg, open(cfg_dst, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    else:
        log(f'  keep      {cfg_dst} (already exists)')

    sp = os.path.join(cd, 'settings.json')
    settings = json.load(open(sp, encoding='utf-8')) if os.path.exists(sp) else {}
    py = a.python.replace('\\', '/')
    hk = os.path.join(cd, 'hooks').replace('\\', '/')
    dispatch = f'"{py}" -I "{hk}/commander_dispatch.py"'
    router = f'"{py}" -I "{hk}/skill_router.py"'
    hooks = settings.setdefault('hooks', {})
    changed = [add_hook(hooks, 'UserPromptSubmit', None, router),
               add_hook(hooks, 'PreToolUse', 'Read|Write|Edit|Bash|PowerShell|Skill|mcp__matlab__.*', dispatch),
               add_hook(hooks, 'Stop', None, dispatch)]
    env = settings.setdefault('env', {})
    if env.get('SLASH_COMMAND_TOOL_CHAR_BUDGET') != '65000':
        env['SLASH_COMMAND_TOOL_CHAR_BUDGET'] = '65000'
        changed.append(True)
    if any(changed):
        if os.path.exists(sp):
            log(f'  backup    {sp}.bak-{STAMP}')
            if not dry:
                shutil.copy2(sp, f'{sp}.bak-{STAMP}')
        log(f'  update    {sp} (hooks + SLASH_COMMAND_TOOL_CHAR_BUDGET)')
        if not dry:
            json.dump(settings, open(sp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    else:
        log(f'  keep      {sp} (already registered)')

    # CLAUDE.md block: keeps 黑哥 on duty at session start and after every compaction (idempotent, marked)
    if not a.no_claude_md:
        cm = os.path.join(cd, 'CLAUDE.md')
        text = open(cm, encoding='utf-8').read() if os.path.exists(cm) else ''
        if BLOCK_START in text:
            log(f'  keep      {cm} (台中黑哥 block already present)')
        else:
            if text:
                log(f'  backup    {cm}.bak-{STAMP}')
                if not dry:
                    shutil.copy2(cm, f'{cm}.bak-{STAMP}')
            log(f'  update    {cm} (append 台中黑哥 block)')
            if not dry:
                with open(cm, 'a', encoding='utf-8') as f:
                    f.write(('\n\n' if text and not text.endswith('\n\n') else '') + CLAUDE_MD_BLOCK)

    log('\n完成。接下來：')
    log('  1. 編輯 ~/.claude/commander/config.json（owner、要不要輸出前審稿、授權專案）')
    log('  2. 編輯 ~/.claude/skills/commander/LOCAL.md（你的常設派工規則）')
    log('  3. 完全關掉 Claude Code 再打開')
    log('  4. 驗收：python ' + os.path.join(cd, 'hooks', 'test_commander_dispatch.py'))


if __name__ == '__main__':
    main()
