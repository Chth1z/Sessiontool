"""按需从原始记录里取大块内容：工具的完整输入输出、图片。

引用格式是 "文件编号.行偏移.块下标"（工具结果里的图片再加一级下标），都来自索引，
所以只能取到会话记录里已有的内容。
"""
import base64
import os
import re

from .index import flatten_result, is_base64_image

PERSISTED = re.compile(r'Full output saved to: ([^\r\n]+)')
LOCAL_IMAGE = re.compile(r'\[Image: source: ([^\]\r\n]+\.(?:png|jpe?g|gif|webp))\]', re.I)
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
    d = index.raw(nums[0], nums[1])
    content = ((d or {}).get('message') or {}).get('content')
    if not isinstance(content, list) or nums[2] >= len(content) or not isinstance(content[nums[2]], dict):
        return None, nums
    return content[nums[2]], nums


def inside_tool_results(sources, path):
    """只允许读会话记录目录下 tool-results 文件夹里的文件。"""
    real = os.path.realpath(path)
    root = os.path.realpath(sources.root)
    try:
        inside = os.path.commonpath([real, root]) == root
    except ValueError:
        inside = False
    return real if inside and os.path.basename(os.path.dirname(real)) == 'tool-results' and os.path.isfile(real) else None


def load_tool(index, sources, use_ref, res_ref=None):
    """→ {name, input, result, error, images, local_images, full}。images 是图片引用，local_images 是磁盘路径。"""
    out = {'name': '', 'input': None, 'result': None, 'error': False, 'images': [], 'local_images': [], 'full': None}
    use, _ = block(index, use_ref)
    if use and use.get('type') == 'tool_use':
        out['name'], out['input'] = use.get('name') or '', use.get('input')
    res, nums = block(index, res_ref) if res_ref else (None, None)
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
    if blk.get('type') != 'image' or not is_base64_image(blk):
        return None
    try:
        data = base64.b64decode(blk['source']['data'])
    except ValueError:
        return None
    media = blk['source'].get('media_type') or 'image/png'
    return data, (media if media in IMAGE_TYPES.values() else 'image/png')


def load_local_image(sources, path):
    real = inside_tool_results(sources, path)
    media = IMAGE_TYPES.get(os.path.splitext(real or '')[1].lower())
    if not real or not media:
        return None
    with open(real, 'rb') as f:
        return f.read(), media
