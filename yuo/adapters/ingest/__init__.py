"""Readers for the learner's own files: PDF (pypdfium2), PowerPoint and Word (their XML, read directly), text.

Each returns `yuo.core.documents.Extracted`: the text with its pages or slides, and the file's own outline.
Recordings are read by `yuo.adapters.tools.ffmpeg` and transcribed separately.
"""

from pathlib import Path

from yuo.adapters.ingest.office import read_docx, read_pptx
from yuo.adapters.ingest.pdf import read_pdf
from yuo.adapters.ingest.text import read_text
from yuo.core.documents import Extracted, ReadError

DOCUMENT_KINDS = {".pdf": "pdf", ".pptx": "pptx", ".docx": "docx", ".md": "text", ".txt": "text"}
MEDIA_KINDS = {
    **{e: "audio" for e in (".mp3", ".m4a", ".wav", ".ogg", ".opus", ".flac", ".aac", ".wma")},
    **{e: "video" for e in (".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".wmv")},
}


def kind_of(file_name: str) -> str | None:
    ext = Path(file_name).suffix.lower()
    return DOCUMENT_KINDS.get(ext) or MEDIA_KINDS.get(ext)


def read_document(path: Path, kind: str) -> Extracted:
    match kind:
        case "pdf":
            return read_pdf(path)
        case "pptx":
            return read_pptx(path)
        case "docx":
            return read_docx(path)
        case "text":
            return read_text(path)
    raise ReadError(f"not a document: {kind}")
