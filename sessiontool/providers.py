"""多来源适配器注册表（Claude / Codex / Gemini 的单一事实来源）。

集中维护各来源的显示名、头像字母、样式类、数据属性名、恢复命令前缀、编辑类工具名与解析模块。
"""
import dataclasses

from . import claude, codex, gemini


@dataclasses.dataclass(frozen=True)
class Provider:
    key: str
    name: str
    initial: str
    cls: str
    attr: str
    resume_prefix: str
    edit_tools: tuple
    module: object

    def file_cli(self, path):
        return self.module.file_cli(path)

    def load_extra(self, path):
        fn = getattr(self.module, 'load_extra', None)
        return fn(path) if fn else None

    def content(self, d):
        return self.module.content(d)


PROVIDERS = {
    'claude': Provider('claude', 'Claude', 'C', '', 'c', 'claude --resume ', claude.EDIT_TOOLS, claude),
    'codex': Provider('codex', 'Codex', 'X', 'cx', 'x', 'codex resume ', codex.EDIT_TOOLS, codex),
    'gemini': Provider('gemini', 'Gemini', 'G', 'gm', 'g', 'agy --conversation ', gemini.EDIT_TOOLS, gemini),
}
PROVIDER_KEYS = tuple(PROVIDERS)
EDIT_TOOLS = frozenset(t for p in PROVIDERS.values() for t in p.edit_tools)


def get(src):
    return PROVIDERS.get(src, PROVIDERS['claude'])
