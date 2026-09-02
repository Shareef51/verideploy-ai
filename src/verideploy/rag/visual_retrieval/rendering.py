from __future__ import annotations
import hashlib
from pathlib import Path
from uuid import UUID, NAMESPACE_URL, uuid5
import fitz
from verideploy.rag.visual_retrieval.schemas import RenderedPage

class PdfPageRenderer:
    def __init__(self, output_root: str | Path, *, dpi: int = 144, max_pages: int = 500) -> None:
        self.output_root = Path(output_root)
        self.dpi = dpi
        self.max_pages = max_pages

    def render(self, *, tenant_id: UUID, document_id: UUID, pdf_bytes: bytes) -> list[RenderedPage]:
        if not pdf_bytes.startswith(b"%PDF"):
            raise ValueError("visual document renderer requires PDF bytes")
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            if doc.page_count > self.max_pages:
                raise ValueError("document exceeds visual page limit")
            target = self.output_root / str(tenant_id) / str(document_id)
            target.mkdir(parents=True, exist_ok=True)
            rendered: list[RenderedPage] = []
            for idx in range(doc.page_count):
                page = doc.load_page(idx)
                pix = page.get_pixmap(dpi=self.dpi, alpha=False)
                raw = pix.tobytes("png")
                sha = hashlib.sha256(raw).hexdigest()
                path = target / f"page-{idx+1:04d}-{sha[:12]}.png"
                path.write_bytes(raw)
                page_id = uuid5(NAMESPACE_URL, f"verideploy:{tenant_id}:{document_id}:page:{idx+1}")
                rendered.append(RenderedPage(
                    page_id=page_id, document_id=document_id, tenant_id=tenant_id, page_number=idx+1,
                    image_path=str(path), image_sha256=sha, width=pix.width, height=pix.height,
                    native_text=page.get_text("text")[:100_000],
                ))
            return rendered
        finally:
            doc.close()
