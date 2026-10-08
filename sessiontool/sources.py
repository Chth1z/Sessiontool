"""数据位置：Claude Code 的会话记录、桌面应用的会话清单、本工具自己的索引。"""
import glob
import json
import os


def default_stores():
    """桌面应用保存会话清单的目录。Windows 商店版把 AppData 重定向到 Packages 下，两处都找。"""
    home = os.path.expanduser('~')
    out = []
    for base in (os.environ.get('APPDATA'), os.path.join(home, 'Library', 'Application Support'),
                 os.path.join(home, '.config')):
        if base:
            out.append(os.path.join(base, 'Claude', 'claude-code-sessions'))
    local = os.environ.get('LOCALAPPDATA')
    if local:
        out += glob.glob(os.path.join(local, 'Packages', 'Claude_*', 'LocalCache', 'Roaming', 'Claude',
                                      'claude-code-sessions'))
    return [d for d in out if os.path.isdir(d)]


class Sources:
    def __init__(self, root=None, stores=None, home=None):
        user = os.path.expanduser('~')
        config = os.environ.get('CLAUDE_CONFIG_DIR') or os.path.join(user, '.claude')
        self.root = os.path.abspath(root or os.path.join(config, 'projects'))
        self.stores = default_stores() if stores is None else list(stores)
        self.home = os.path.abspath(home or os.environ.get('SESSIONTOOL_HOME') or os.path.join(user, '.sessiontool'))

    def transcripts(self):
        return sorted(glob.glob(os.path.join(self.root, '*', '*.jsonl')))

    def app_sessions(self):
        """应用的会话清单：{sessionId: 记录}。一个会话在多个目录出现时取最近活动的那份。"""
        out = {}
        for d in self.stores:
            for p in glob.glob(os.path.join(d, '**', 'local_*.json'), recursive=True):
                try:
                    with open(p, encoding='utf-8') as f:
                        r = json.load(f)
                except (OSError, ValueError):
                    continue
                if not isinstance(r, dict) or not r.get('sessionId') or not r.get('cliSessionId'):
                    continue
                old = out.get(r['sessionId'])
                if not old or (r.get('lastActivityAt') or 0) >= (old.get('lastActivityAt') or 0):
                    out[r['sessionId']] = r
        return out
