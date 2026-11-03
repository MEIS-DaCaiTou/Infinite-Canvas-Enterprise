"""Limits for user workflow import, independent of release-package contracts."""
from fastapi import HTTPException

MAX_UPLOAD = 256 * 1024 * 1024
MAX_WORKFLOW = 8 * 1024 * 1024
MAX_RESOURCE = 256 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
MAX_ENTRIES = 2048


def inspect_archive(archive):
    entries = archive.infolist()
    if len(entries) > MAX_ENTRIES or sum(x.file_size for x in entries) > MAX_EXPANDED:
        raise HTTPException(413, '工作流压缩包展开内容过大或文件过多，请拆分后导入')
    names = set()
    for item in entries:
        if item.filename in names or item.flag_bits & 1:
            raise HTTPException(400, '工作流压缩包包含重复名称或加密文件')
        names.add(item.filename)
        if item.file_size > MAX_RESOURCE or item.file_size > max(1, item.compress_size) * 1000:
            raise HTTPException(413, '工作流压缩包单文件过大或压缩比异常')


def copy_resource(source, dest, total):
    size = 0
    while chunk := source.read(256 * 1024):
        size += len(chunk)
        total += len(chunk)
        if size > MAX_RESOURCE or total > MAX_EXPANDED:
            raise HTTPException(413, '工作流素材展开大小超限')
        dest.write(chunk)
    return total
