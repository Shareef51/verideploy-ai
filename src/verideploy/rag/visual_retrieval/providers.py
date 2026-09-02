from __future__ import annotations
import hashlib, math
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
from PIL import Image, ImageFilter, ImageStat
from verideploy.rag.visual_retrieval.schemas import RenderedPage, VisualBackend

class VisualRetrieverAdapter(ABC):
    backend: VisualBackend
    model_name: str
    @abstractmethod
    def index_page(self, page: RenderedPage) -> Any: ...
    @abstractmethod
    def score(self, query: str, indexed: Any) -> float: ...

class CpuVisualFallbackAdapter(VisualRetrieverAdapter):
    """CPU-safe fallback: native PDF text hashing + rendered-page visual statistics. No OCR."""
    backend = VisualBackend.CPU_FALLBACK
    model_name = "verideploy-cpu-visual-signature-v1"
    dims = 256

    @staticmethod
    def _hash_tokens(text: str, dims: int = 224) -> list[float]:
        vec = [0.0] * dims
        for token in text.lower().replace("/", " ").replace("-", " ").split():
            token = ''.join(ch for ch in token if ch.isalnum() or ch in {'_', '.'})
            if not token: continue
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            slot = int.from_bytes(digest[:4], "big") % dims
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[slot] += sign
        norm = math.sqrt(sum(x*x for x in vec)) or 1.0
        return [x/norm for x in vec]

    @staticmethod
    def _visual_features(path: str) -> list[float]:
        with Image.open(path) as im:
            im = im.convert("RGB")
            original_aspect = min(3.0, im.width / max(1, im.height)) / 3.0
            im = im.resize((128, 128))
            gray = im.convert("L")
            edge = gray.filter(ImageFilter.FIND_EDGES)
            stat = ImageStat.Stat(im); gstat = ImageStat.Stat(gray); estat = ImageStat.Stat(edge)
            hist = gray.histogram()
            bins = [sum(hist[i:i+32]) / (128*128) for i in range(0,256,32)]
            means = [m/255.0 for m in stat.mean]
            stds = [s/128.0 for s in stat.stddev]
            edge_mean = estat.mean[0]/255.0
            brightness = gstat.mean[0]/255.0
            aspect = original_aspect
            color_spread = (max(means)-min(means))
            feats = means + stds + [edge_mean, brightness, aspect, color_spread] + bins
            # category slots: diagram-like, dashboard/chart-like, text-heavy proxy, table/grid-like
            diagram = min(1.0, edge_mean*4 + color_spread)
            dashboard = min(1.0, edge_mean*3 + sum(stds)/3)
            text_heavy = min(1.0, edge_mean*5)
            grid = min(1.0, edge_mean*6 + (1-brightness)*0.2)
            feats += [diagram,dashboard,text_heavy,grid]
            while len(feats) < 32: feats.append(0.0)
            return feats[:32]

    def index_page(self, page: RenderedPage) -> list[float]:
        return self._hash_tokens(page.native_text) + self._visual_features(page.image_path)

    def _query_vector(self, query: str) -> list[float]:
        text = self._hash_tokens(query)
        q = query.lower()
        vis = [0.0]*32
        if any(x in q for x in ("architecture","dependency","service","diagram","topology")): vis[-4]=1.0
        if any(x in q for x in ("dashboard","chart","grafana","metric","latency","graph")): vis[-3]=1.0
        if any(x in q for x in ("text","runbook","paragraph")): vis[-2]=1.0
        if any(x in q for x in ("table","grid","matrix")): vis[-1]=1.0
        return text + vis

    def score(self, query: str, indexed: list[float]) -> float:
        q = self._query_vector(query)
        # text dominates fallback semantics; visual category signal remains material.
        dot = sum(a*b for a,b in zip(q,indexed))
        nq = math.sqrt(sum(a*a for a in q)) or 1.0
        nd = math.sqrt(sum(a*a for a in indexed)) or 1.0
        return dot/(nq*nd)

class ColPaliAdapter(VisualRetrieverAdapter):
    """Optional Hugging Face native ColPali late-interaction adapter."""
    backend = VisualBackend.COLPALI
    def __init__(self, model_name: str = "vidore/colpali-v1.3-hf", device: str = "cpu") -> None:
        try:
            import torch
            from transformers import ColPaliForRetrieval, ColPaliProcessor
        except ImportError as exc:
            raise RuntimeError("ColPali requires transformers and torch optional dependencies") from exc
        self._torch = torch
        self.model_name = model_name
        self.model = ColPaliForRetrieval.from_pretrained(model_name, device_map=device).eval()
        self.processor = ColPaliProcessor.from_pretrained(model_name)

    def index_page(self, page: RenderedPage):
        with Image.open(Path(page.image_path)) as image:
            inputs = self.processor(images=[image.convert("RGB")]).to(self.model.device)
            with self._torch.no_grad():
                return self.model(**inputs).embeddings.detach().cpu()

    def score(self, query: str, indexed) -> float:
        inputs = self.processor(text=[query]).to(self.model.device)
        with self._torch.no_grad():
            q = self.model(**inputs).embeddings.detach().cpu()
        if hasattr(self.processor, "score_retrieval"):
            score = self.processor.score_retrieval(q, indexed)
            return float(score[0][0])
        # MaxSim late interaction fallback compatible with ColBERT-style embeddings.
        sim = q[0] @ indexed[0].T
        return float(sim.max(dim=1).values.sum().item())
