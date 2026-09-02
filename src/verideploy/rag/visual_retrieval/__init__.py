__all__=["ColPaliAdapter","CpuVisualFallbackAdapter","PdfPageRenderer","VisualDocumentService"]


def __getattr__(name):
    """Keep optional PDF/ML dependencies lazy for workers that only use graph schemas."""
    if name in {"ColPaliAdapter", "CpuVisualFallbackAdapter"}:
        from verideploy.rag.visual_retrieval.providers import ColPaliAdapter, CpuVisualFallbackAdapter
        return {"ColPaliAdapter": ColPaliAdapter, "CpuVisualFallbackAdapter": CpuVisualFallbackAdapter}[name]
    if name == "PdfPageRenderer":
        from verideploy.rag.visual_retrieval.rendering import PdfPageRenderer
        return PdfPageRenderer
    if name == "VisualDocumentService":
        from verideploy.rag.visual_retrieval.service import VisualDocumentService
        return VisualDocumentService
    raise AttributeError(name)
