# Visual & Multimodal Metrics

Visual Multimodal Metrics adds deterministic modality-specific evaluation for VeriDeploy AI's visual and temporal evidence paths.

## Metrics

- **Image grounding accuracy** — F1 over expected vs observed regions/entities.
- **Screenshot/diagram understanding** — F1 over expected vs observed visual facts and topology.
- **OCR-free visual reasoning** — validates reasoning from visual evidence without depending on OCR text.
- **Multimodal citation correctness** — F1 over image/page/audio/video evidence references.
- **Temporal alignment** — timestamp alignment score plus mean absolute timing error for audio/video anchors.
- **Modality gates** — image, screenshot, diagram, audio, and video each have independent quality thresholds.

The benchmark uses the existing 500-case synthetic evaluation corpus and deterministically assigns a modality profile without changing 500 Case Evaluation Dataset category labels. CI requires the overall gate and every modality gate to pass.
