"""Optional local LaMa engine. Importing this module never loads a model or uses a network.

Supports Carve/LaMa-ONNX's lama_fp32.onnx: RGB float32 0..1 and a white-to-erase
binary mask, both NCHW at 512x512; output is RGB NCHW *already* in 0..255.
Contract: https://github.com/Carve-Photos/lama/blob/main/export_LaMa_to_onnx.ipynb
"""
from __future__ import annotations

import importlib.util
import hashlib
import os
from pathlib import Path
import sys
import threading

from PIL import Image
from .platform_support import default_data_dir

MODEL_FILENAME = "lama_fp32.onnx"
MODEL_REVISION = "a3ee2fca54baebec351b8fa7786154ffa7555aa6"
MODEL_SHA256 = "1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6"
MODEL_BYTES = 208044816
MODEL_URL = f"https://huggingface.co/Carve/LaMa-ONNX/resolve/{MODEL_REVISION}/{MODEL_FILENAME}"
MODEL_ENV = "CHIPDF_LAMA_MODEL"
TILE_SIZE = 512
CORE_SIZE = 256
_session_lock = threading.Lock()
_session_key = None
_session = None


class LamaUnavailableError(RuntimeError):
    """A model or its optional runtime needs the user's attention."""


def _model_candidates(model_path=None):
    override = model_path or os.environ.get(MODEL_ENV)
    if override:
        # A broken explicitly selected path is an error, never another model.
        return [Path(override).expanduser()]
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    roots = [root]
    if getattr(sys, "frozen", False):
        roots.insert(0, Path(sys.executable).resolve().parent)
    candidates = []
    for folder in roots:
        candidates += [folder / "vendor/models/inpaint" / MODEL_FILENAME,
                       folder / "models/inpaint" / MODEL_FILENAME]
    candidates.append(default_data_dir() / "models/inpaint" / MODEL_FILENAME)
    return candidates


def resolve_lama_model(model_path=None):
    candidates = _model_candidates(model_path)
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    raise LamaUnavailableError(
        "LaMa 모델 파일이 없습니다. '지우기 설정 → 파일 선택'에서 lama_fp32.onnx를 선택하거나 "
        f"다음 위치에 넣어 주세요:\n{candidates[0]}\n"
        "소스 실행 환경에서는 python prepare_inpaint.py --download로 준비할 수 있습니다."
    )


def lama_status(model_path=None):
    """Cheap presence check, not an inference or a model-integrity check."""
    runtime_available = importlib.util.find_spec("onnxruntime") is not None
    try:
        path = resolve_lama_model(model_path)
        model_available, message = True, "LaMa 모델 파일과 실행 모듈이 있습니다. 첫 복원에서 모델을 확인합니다."
    except LamaUnavailableError as exc:
        path, model_available, message = _model_candidates(model_path)[0], False, str(exc)
    if not runtime_available:
        message = ("LaMa 실행 모듈이 없습니다. LaMa 지원 배포본을 사용하거나 소스 실행 환경에서 "
                   "python -m pip install --target .deps -r requirements-inpaint.txt를 실행해 주세요."
                   + ("\n" + message if not model_available else ""))
    return {"available": model_available and runtime_available, "model_path": str(path),
            "runtime_available": runtime_available, "model_available": model_available,
            "message": message}


def _get_session(model_path=None):
    global _session_key, _session
    path = resolve_lama_model(model_path)
    metadata = path.stat()
    key = (str(path), metadata.st_size, metadata.st_mtime_ns)
    with _session_lock:
        if _session is not None and key == _session_key:
            return _session
        if metadata.st_size != MODEL_BYTES:
            raise LamaUnavailableError('지원하는 LaMa 모델과 파일 크기가 다릅니다. lama_fp32.onnx를 다시 연결해 주세요.')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != MODEL_SHA256:
            raise LamaUnavailableError('LaMa 모델 파일이 다르거나 손상되었습니다. prepare_inpaint.py로 준비한 파일을 연결해 주세요.')
        try:
            import onnxruntime as ort
        except (ImportError, OSError) as exc:
            raise LamaUnavailableError(
                "LaMa 실행 모듈을 불러올 수 없습니다. LaMa 지원 배포본을 사용하거나 "
                "python -m pip install --target .deps -r requirements-inpaint.txt로 설치해 주세요.\n"
                f"상세: {exc}"
            ) from exc
        try:
            options = ort.SessionOptions()
            options.intra_op_num_threads = min(4, max(1, (os.cpu_count() or 2) - 1))
            options.inter_op_num_threads = 1
            # Cache at most one potentially large model per process.
            _session, _session_key = None, None
            session = ort.InferenceSession(str(path), sess_options=options,
                                           providers=["CPUExecutionProvider"])
            inputs = {item.name: item for item in session.get_inputs()}
            for name, channels in (("image", 3), ("mask", 1)):
                item = inputs.get(name)
                if (item is None or item.type != "tensor(float)" or len(item.shape) != 4
                        or list(item.shape[1:]) != [channels, TILE_SIZE, TILE_SIZE]):
                    raise ValueError("512×512 image/mask 입력 형식이 다릅니다")
            if set(inputs) != {"image", "mask"}:
                raise ValueError("지원하지 않는 추가 모델 입력이 있습니다")
        except Exception as exc:
            raise LamaUnavailableError(
                "LaMa 모델을 열 수 없습니다. Carve/LaMa-ONNX의 lama_fp32.onnx 파일을 "
                f"다시 선택하거나 준비해 주세요.\n상세: {exc}"
            ) from exc
        _session, _session_key = session, key
        return session


def _check_cancel(cancelled):
    if cancelled is not None:
        stopped = cancelled() if callable(cancelled) else cancelled.is_set()
        if stopped:
            raise InterruptedError("LaMa 배경 복원을 취소했습니다.")


def _crop_boxes(mask):
    """Place native-resolution contextual crops around occupied 256px cores."""
    bbox = mask.getbbox()
    if bbox is None:
        return []
    width, height = mask.size
    left, top, right, bottom = bbox
    cores = [(left, top, right, bottom)] if right-left <= CORE_SIZE and bottom-top <= CORE_SIZE else (
        (x, y, min(x + CORE_SIZE, right), min(y + CORE_SIZE, bottom))
        for y in range(top, bottom, CORE_SIZE) for x in range(left, right, CORE_SIZE))
    boxes = {}
    for core in cores:
        occupied = mask.crop(core).getbbox()
        if occupied is None:
            continue
        cx = core[0] + (occupied[0] + occupied[2]) // 2
        cy = core[1] + (occupied[1] + occupied[3]) // 2
        x = max(0, min(cx - TILE_SIZE // 2, width - TILE_SIZE))
        y = max(0, min(cy - TILE_SIZE // 2, height - TILE_SIZE))
        boxes[(x, y, min(width, x + TILE_SIZE), min(height, y + TILE_SIZE))] = None
    return list(boxes)


def restore_lama(source, mask, cancelled=None, progress=None, model_path=None):
    """Restore white/nonzero mask pixels, preserving all other RGB and all alpha.

    Every overlapping 512px crop uses the unchanged source. Predictions are
    feather-combined only inside the binary mask; the full page is never resized.
    ``cancelled`` is a callable or Event; ``progress`` receives one Korean string.
    Cancellation is checked between crops (an active ONNX run cannot be stopped).
    """
    import numpy as np

    if source.size != mask.size:
        raise ValueError("복원 이미지와 선택 마스크의 크기가 다릅니다.")
    _check_cancel(cancelled)
    binary = mask.convert("L").point(lambda value: 255 if value else 0)
    boxes = _crop_boxes(binary)
    if not boxes:
        return source.copy()
    if progress:
        progress("LaMa 로컬 모델을 준비하는 중입니다…")
    session = _get_session(model_path)
    _check_cancel(cancelled)
    original = np.asarray(source.convert("RGBA"))
    result = original.copy()
    allowed = np.asarray(binary) != 0
    bounds = binary.getbbox()
    bx, by, br, bb = bounds
    # Weight memory is limited to the selection bounds; model tensors are 512px.
    weights = np.zeros((bb-by, br-bx), dtype=np.float32)
    ramp = np.minimum(np.arange(1, TILE_SIZE+1), np.arange(TILE_SIZE, 0, -1))
    feather = np.minimum(ramp, TILE_SIZE // 4).astype(np.float32)
    feather = np.minimum(feather[:, None], feather[None, :]) / (TILE_SIZE // 4)
    for number, (x, y, right, bottom) in enumerate(boxes, 1):
        _check_cancel(cancelled)
        if progress:
            progress(f"LaMa 배경 복원 중… {number}/{len(boxes)}")
        h, w = bottom-y, right-x
        rgb = original[y:bottom, x:right, :3]
        selected = allowed[y:bottom, x:right]
        # Symmetric padding preserves context for tiny images without stretching.
        rgb = np.pad(rgb, ((0, TILE_SIZE-h), (0, TILE_SIZE-w), (0, 0)), mode="symmetric")
        selected = np.pad(selected, ((0, TILE_SIZE-h), (0, TILE_SIZE-w)), mode="symmetric")
        image_tensor = np.ascontiguousarray(rgb.transpose(2, 0, 1)[None], dtype=np.float32) / 255.0
        mask_tensor = np.ascontiguousarray(selected[None, None], dtype=np.float32)
        try:
            output = session.run(None, {"image": image_tensor, "mask": mask_tensor})[0]
        except Exception as exc:
            raise RuntimeError(f"LaMa 배경 복원에 실패했습니다. 선택 영역을 줄여 다시 시도해 주세요.\n상세: {exc}") from exc
        _check_cancel(cancelled)
        if output.shape != (1, 3, TILE_SIZE, TILE_SIZE) or not np.isfinite(output).all():
            raise RuntimeError("LaMa 모델의 출력 형식이 올바르지 않습니다. lama_fp32.onnx 파일을 확인해 주세요.")
        # Carve's export already multiplies its output by 255.
        prediction = np.clip(output[0].transpose(1, 2, 0), 0, 255)
        ix, iy, ir, ib = max(x, bx), max(y, by), min(right, br), min(bottom, bb)
        local = (slice(iy-y, ib-y), slice(ix-x, ir-x))
        chosen = allowed[iy:ib, ix:ir]
        old_weight = weights[iy-by:ib-by, ix-bx:ir-bx]
        new_weight = feather[local] * chosen
        denominator = old_weight + new_weight
        pixels = result[iy:ib, ix:ir, :3]
        combined = (pixels[chosen].astype(np.float32) * old_weight[chosen, None]
                    + prediction[local][chosen] * new_weight[chosen, None]) / denominator[chosen, None]
        pixels[chosen] = np.rint(combined).astype(np.uint8)
        old_weight[:] = denominator
    _check_cancel(cancelled)
    if progress:
        progress("LaMa 배경 복원이 완료되었습니다.")
    restored = Image.fromarray(result)
    return restored.convert("RGB") if source.mode == "RGB" else restored
