# OCR foundation

M0.3b.2 defines a small, source-neutral OCR boundary. A caller supplies an immutable `Frame`, its
matching `ContentViewport`, and either a `NormalizedRoi` or a `PixelRoi` entirely inside that
viewport. `recognize_text` copies only that resolved BGR crop before passing it to an async
`OcrBackend`; neither the original frame nor any domain state can be modified.

`OcrResult` records raw text, NFKC/whitespace-normalized text, optional backend confidence,
recognized/empty/unknown status, resolved raw-frame pixel bounds, and complete frame/source
provenance, including the aware processing timestamp and optional source timestamp. `None` raw
text means unknown; blank normalized text means the backend completed but found no text. This
module deliberately does not parse `name#XXXX`, strategy names, or any game screen semantics.

The included `WindowsOcrBackend` uses the Windows OCR component via the small Python/WinRT binding
packages. It does not require or invoke Tesseract or another external executable/model runtime.
The requested BCP-47 language (normally `ja-JP`) must be installed as a Windows OCR capability;
otherwise it raises `OcrBackendUnavailableError` instead of guessing. The Windows result supplies
text but no confidence, so confidence is `None` for that backend.
