"""按需从原始记录里取大块内容：工具的完整输入输出、图片。

引用格式是 "文件编号.行偏移.块下标"（工具结果里的图片再加一级下标），都来自索引，
所以只能取到会话记录里已有的内容。各来源通过 providers 适配器统一转换成相同块结构后再取。
"""
import base64
import os
import re

from . import providers
from .claude import LOCAL_IMAGE
from .util import flatten_result, is_base64_image

PERSISTED = re.compile(r'Full output saved to: ([^\r\n]+)')
MAX_TEXT = 2_000_000
IMAGE_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp'}


def parse_ref(ref, parts=(3,)):
    try:
        nums = [int(x) for x in ref.split('.')]
    except (ValueError, AttributeError):
        return None
    return nums if len(nums) in parts and all(n >= 0 for n in nums) else None


def block(index, ref, parts=(3,)):
    nums = parse_ref(ref, parts)
    if not nums:
        return None, None
    d, src = index.raw(nums[0], nums[1])
    content = providers.get(src).content(d if isinstance(d, dict) else {})
    if not isinstance(content, list) or nums[2] >= len(content) or not isinstance(content[nums[2]], dict):
        return None, nums
    return content[nums[2]], nums


def _inside(roots, path):
    """确认 path 是存在于任一 roots 根目录之内的常规文件，防止路径穿越。"""
    real = os.path.realpath(path)
    if not os.path.isfile(real):
        return None
    for base in roots:
        root = os.path.realpath(base)
        try:
            if os.path.commonpath([real, root]) == root:
                return real
        except ValueError:
            continue
    return None


def inside_tool_results(sources, path):
    """只允许读会话记录目录下 tool-results 文件夹里的文件。"""
    real = _inside((sources.root,), path)
    return real if real and os.path.basename(os.path.dirname(real)) == 'tool-results' else None


def inside_gemini(sources, path):
    """只允许读 Gemini（Antigravity）数据目录里的媒体文件。"""
    return _inside([d for d, _ in sources.gemini_dirs()], path)


def load_tool(index, sources, use_ref, res_ref=None):
    """→ {name, input, result, error, images, local_images, full}。images 是图片引用，local_images 是磁盘路径。"""
    out = {'name': '', 'input': None, 'result': None, 'error': False, 'images': [], 'local_images': [], 'full': None}
    use, _ = block(index, use_ref)
    if use and use.get('type') == 'tool_use':
        out['name'], out['input'] = use.get('name') or '', use.get('input')
    res, _ = block(index, res_ref) if res_ref else (None, None)
    if res and res.get('type') == 'tool_result':
        text, images = flatten_result(res.get('content'))
        out['error'] = bool(res.get('is_error'))
        out['images'] = ['%s.%d' % (res_ref, j) for j in images]
        m = PERSISTED.search(text)
        if m:
            path = inside_tool_results(sources, m.group(1).strip())
            if path:
                try:
                    with open(path, encoding='utf-8', errors='replace') as f:
                        out['full'] = f.read(MAX_TEXT)
                except OSError:
                    pass
        for m in LOCAL_IMAGE.finditer(text):
            path = inside_tool_results(sources, m.group(1).strip())
            if path and path not in out['local_images']:
                out['local_images'].append(path)
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT] + '\n…（过长，已截断）'
        out['result'] = text
    return out


def load_image(index, ref):
    """→ (字节, 媒体类型) 或 None。"""
    blk, nums = block(index, ref, parts=(3, 4))
    if blk is None:
        return None
    if len(nums) == 4:
        inner = blk.get('content')
        if not isinstance(inner, list) or nums[3] >= len(inner) or not isinstance(inner[nums[3]], dict):
            return None
        blk = inner[nums[3]]
    if blk.get('type') != 'image':
        return None
    src = blk.get('source') or {}
    if is_base64_image(blk):
        try:
            data = base64.b64decode(src['data'])
        except ValueError:
            return None
        media = src.get('media_type') or 'image/png'
        return data, (media if media in IMAGE_TYPES.values() else 'image/png')
    if src.get('type') == 'file' and isinstance(src.get('path'), str):
        real = inside_gemini(index.sources, src['path'])
        if not real:
            return None
        media = src.get('media_type')
        if media not in IMAGE_TYPES.values():
            media = IMAGE_TYPES.get(os.path.splitext(real)[1].lower())
        if not media:
            return None
        try:
            with open(real, 'rb') as f:
                return f.read(), media
        except OSError:
            return None
    return None


def load_sent_image(index, ref):
    """SendUserFile 发给你的图片。引用是 "文件.偏移.块.第几个文件"，路径取自记录本身，不接受外部传入。"""
    blk, nums = block(index, ref, parts=(4,))
    if blk is None or blk.get('type') != 'tool_use' or blk.get('name') != 'SendUserFile':
        return None
    files = (blk.get('input') or {}).get('files')
    if not isinstance(files, list) or nums[3] >= len(files) or not isinstance(files[nums[3]], str):
        return None
    path = files[nums[3]]
    media = IMAGE_TYPES.get(os.path.splitext(path)[1].lower())
    if not media or not os.path.isfile(path):
        return None
    with open(path, 'rb') as f:
        return f.read(), media


def load_local_image(sources, path):
    real = inside_tool_results(sources, path)
    media = IMAGE_TYPES.get(os.path.splitext(real or '')[1].lower())
    if not real or not media:
        return None
    with open(real, 'rb') as f:
        return f.read(), media
