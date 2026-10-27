"""
升级点2：结构感知 + 表格原子保护 的条款切分器（纯逻辑，不依赖数据库/向量模型）。

设计要点
- 按 markdown 标题栈（h1~h6）切出章节，连续的 ``| ... |`` 表格行聚成一个
  「原子表格块」，任何后续尺寸切分都不会把它劈开。
- 父块（喂给大模型的整段内容）做尺寸治理：正文按句子边界打包到目标长度，
  设硬上限；表格块不受长度限制、整块保留。
- 短块只在「同一小节内的相邻段落」之间合并，绝不跨小标题合并（保住语义边界）。
- 每个父块有确定性 chunk_id（uuid5）和内容指纹 content_hash：
  同一份资料反复入库 id 稳定，内容不变指纹不变，支撑增量入库。
"""
from __future__ import annotations

import re
import uuid
import hashlib
from dataclasses import dataclass

# 尺寸参数
TARGET_CHARS = 700     # 正文父块目标长度
MAX_TEXT_CHARS = 1000  # 正文父块硬上限（表格不受此限）
MIN_MERGE_CHARS = 120  # 同小节尾部碎块低于它，则并入上一正文块

_HEADER_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$")
_SEPARATOR_ROW = re.compile(r"^\s*\|?\s*:?-{2,}[\s:\-\|]*\|?\s*$")
# 句末标点后切句（中英文）
_SENT_SPLIT = re.compile(r"(?<=[。；！？;!?)）])")
# 目录标题：标题文字很短且含“目录”
_TOC_TITLE = re.compile(r"^目录$|目\s*录")


@dataclass
class ChunkData:
    """一个父块的切分结果。"""

    chunk_id: uuid.UUID
    content_hash: str
    doc_type: str          # 'text' | 'table'
    chunk_index: int       # 章节内序号（同一 section_path 下从 1 开始）
    section_path: list[str]
    content: str
    table_rows: int = 0

    @property
    def section_path_text(self) -> str:
        """供 Milvus 标量字段 / 展示用的拼接路径。"""
        return " > ".join(self.section_path)


@dataclass
class _Block:
    type: str
    text: str
    path: list


def _clean_lines(lines: list[str]) -> list[str]:
    """去零宽字符/BOM；跳过目录区（直到遇到第一个带编号的正文标题）。表格行原样保留。"""
    cleaned: list[str] = []
    in_toc = False
    for raw in lines:
        ln = raw.replace("​", "").replace("﻿", "").rstrip()
        h = _HEADER_RE.match(ln)
        if h and _TOC_TITLE.search(h.group(2)) and len(h.group(2)) <= 6:
            in_toc = True
            continue
        if in_toc:
            # 进入正文的标志：## 1 / # 第一章 这类编号标题
            if re.match(r"^#{1,2}\s+\d", ln) or re.match(r"^##\s+第?[一二三四0-9]", ln):
                in_toc = False
            else:
                continue
        cleaned.append(ln)
    return cleaned


def _parse_blocks(lines: list[str]) -> list[_Block]:
    """按标题栈切结构，连续表格行聚成一个原子 table block。"""
    blocks: list[_Block] = []
    stack: dict[int, str] = {}
    pending_text: list[str] = []

    def cur_path() -> list[str]:
        # 跳过 h1（文档名），章节路径从 h2 开始
        return [title for level, title in sorted(stack.items()) if level > 1]

    def flush_text() -> None:
        if not pending_text:
            return
        txt = "\n".join(pending_text).strip()
        txt = re.sub(r"\n{3,}", "\n\n", txt)
        if txt:
            blocks.append(_Block("text", txt, cur_path()))
        pending_text.clear()

    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        h = _HEADER_RE.match(ln)
        if h:
            flush_text()
            level = len(h.group(1))
            title = h.group(2).strip()
            stack = {lv: t for lv, t in stack.items() if lv < level}
            stack[level] = title
            i += 1
            continue
        if _TABLE_LINE.match(ln):
            flush_text()
            tbl: list[str] = []
            while i < n and (_TABLE_LINE.match(lines[i]) or _SEPARATOR_ROW.match(lines[i])):
                # 分隔行（| --- | --- |）不入库，只用来识别表格
                if not _SEPARATOR_ROW.match(lines[i]):
                    tbl.append(lines[i].strip())
                i += 1
            if tbl:
                blocks.append(_Block("table", "\n".join(tbl), cur_path()))
            continue
        pending_text.append(ln)
        i += 1
    flush_text()
    return blocks


def _pack_text(paras: list[str], path: list[str], start_index: int) -> tuple[list[ChunkData], int]:
    """把同章节文本段落打包成不超过硬上限的块，目标长度 TARGET，保护句子。"""
    # 先把超长段落按句子拆成不超限的单元
    units: list[str] = []
    for p in paras:
        if len(p) <= MAX_TEXT_CHARS:
            units.append(p)
            continue
        buf = ""
        for sent in [s for s in _SENT_SPLIT.split(p) if s]:
            if len(buf) + len(sent) <= MAX_TEXT_CHARS:
                buf += sent
            else:
                if buf:
                    units.append(buf)
                # 单句本身超长时硬切（保险条款里几乎不会出现）
                while len(sent) > MAX_TEXT_CHARS:
                    units.append(sent[:MAX_TEXT_CHARS])
                    sent = sent[MAX_TEXT_CHARS:]
                buf = sent
        if buf:
            units.append(buf)

    proto: list[tuple[str, int]] = []  # (content, index 占位)
    buf = ""

    def push(text: str) -> None:
        proto.append((text.strip(), 0))

    for u in units:
        if buf and len(buf) + 1 + len(u) > TARGET_CHARS:
            push(buf)
            buf = ""
        buf = (buf + "\n" + u).strip() if buf else u
        if len(buf) >= TARGET_CHARS:
            push(buf)
            buf = ""
    if buf:
        push(buf)

    # 同小节尾部碎块并入上一块（合并不超过硬上限）
    if len(proto) >= 2 and len(proto[-1][0]) < MIN_MERGE_CHARS:
        merged = proto[-2][0] + "\n" + proto[-1][0]
        if len(merged) <= MAX_TEXT_CHARS:
            proto[-2] = (merged, 0)
            proto.pop()

    chunks: list[ChunkData] = []
    idx = start_index
    for content, _ in proto:
        chunks.append(
            ChunkData(
                chunk_id=uuid.UUID(int=0),  # 占位，后面统一赋确定性 id
                content_hash="",
                doc_type="text",
                chunk_index=idx,
                section_path=path,
                content=content,
            )
        )
        idx += 1
    return chunks, idx


def split_clause(markdown: str, product_id: int, clause_stem: str) -> list[ChunkData]:
    """
    把一份条款 markdown 切成父块列表（保持文档顺序）。

    :param markdown: 条款 markdown 全文
    :param product_id: 产品 id（参与确定性 id 计算；共用条款的不同产品各自独立）
    :param clause_stem: 条款文件名（去扩展名）
    """
    lines = _clean_lines(markdown.splitlines())
    blocks = _parse_blocks(lines)

    chunks: list[ChunkData] = []
    i, n = 0, len(blocks)
    while i < n:
        path = blocks[i].path
        j = i
        while j < n and blocks[j].path == path:
            j += 1

        idx = 1
        text_paras: list[str] = []

        def flush_texts() -> None:
            nonlocal idx
            if text_paras:
                cs, idx = _pack_text(text_paras, path, idx)
                chunks.extend(cs)
                text_paras.clear()

        for b in blocks[i:j]:
            if b.type == "text":
                text_paras.append(b.text)
            else:
                flush_texts()
                chunks.append(
                    ChunkData(
                        chunk_id=uuid.UUID(int=0),
                        content_hash="",
                        doc_type="table",
                        chunk_index=idx,
                        section_path=path,
                        content=b.text,
                        table_rows=len(b.text.splitlines()),
                    )
                )
                idx += 1
        flush_texts()
        i = j

    # 赋确定性 id 与内容指纹
    for c in chunks:
        c.chunk_id = deterministic_chunk_id(product_id, clause_stem, c.section_path, c.chunk_index)
        c.content_hash = content_hash(c.content)
    return chunks


def deterministic_chunk_id(
    product_id: int, clause_stem: str, section_path: list[str], chunk_index: int
) -> uuid.UUID:
    """同一份资料、同一章节、同一块序号，每次算出相同 uuid。"""
    key = f"{product_id}|{clause_stem}|{'/'.join(section_path)}|{chunk_index}"
    return uuid.uuid5(uuid.NAMESPACE_URL, key)


def content_hash(text: str) -> str:
    """内容指纹：归一化空白后取 sha256 前 16 位。"""
    normalized = re.sub(r"\s+", "", text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
