"""
知识库上传文件存储工具: 文件名净化、唯一 stem、原子写盘、格式校验。
"""
import os
import tempfile
import unicodedata
from pathlib import Path
from uuid import uuid4

SUPPORTED_EXTENSIONS = {".md", ".pdf"}
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
INVALID_FILENAME_CHARS = set('<>:"|?*')


class StorageError(ValueError):
    """上传文件校验失败"""


def sanitize_filename(filename: str) -> tuple[str, str]:
    """
    把客户端文件名净化成安全的 stem 和扩展名。

    :return: (stem, ext), ext 小写并带点
    """
    name = (filename or "").replace("\\", "/").split("/")[-1]
    name = unicodedata.normalize("NFKC", name)

    # 去掉控制字符和 Windows 非法字符
    cleaned = "".join(
        char for char in name
        if ord(char) >= 32 and char not in INVALID_FILENAME_CHARS
    )
    cleaned = cleaned.strip(" .")
    if not cleaned or cleaned in {".", ".."}:
        raise StorageError("文件名不合法")

    path = Path(cleaned)
    ext = path.suffix.lower()
    stem = path.stem.strip(" .")
    if not stem:
        stem = "document"

    # Windows 保留名加前缀
    if stem.upper().split(".")[0] in WINDOWS_RESERVED:
        stem = f"_{stem}"

    if len(stem) > 80:
        stem = stem[:80].rstrip(" .")
    if not stem:
        stem = "document"

    return stem, ext


def build_storage_stem(filename: str) -> tuple[str, str]:
    """生成唯一 storage_stem: 净化名 + 8 位 uuid 后缀"""
    stem, ext = sanitize_filename(filename)
    if ext not in SUPPORTED_EXTENSIONS:
        raise StorageError("只支持 .md 和 .pdf 文件")
    return f"{stem}-{uuid4().hex[:8]}", ext


def validate_markdown(data: bytes) -> str:
    """校验并解码 Markdown, 统一换行符"""
    if b"\x00" in data:
        raise StorageError("Markdown 文件包含二进制内容")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise StorageError("Markdown 文件必须使用 UTF-8 编码") from exc
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise StorageError("Markdown 文件内容为空")
    return text


def validate_pdf(data: bytes) -> None:
    if not data.startswith(b"%PDF-"):
        raise StorageError("文件不是有效的 PDF")


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """同目录临时文件 + os.replace, 保证流水线不会读到半个文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".upload-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def resolve_upload_path(base_dir: Path, filename: str) -> Path:
    """拼出最终路径并确保不会越出目标目录"""
    path = (base_dir / filename).resolve()
    if not path.is_relative_to(base_dir.resolve()):
        raise StorageError("文件路径越界")
    return path


def ensure_storage_dirs(md_dir: Path, pdf_dir: Path, tmp_dir: Path) -> None:
    for directory in (md_dir, pdf_dir, tmp_dir):
        directory.mkdir(parents=True, exist_ok=True)
