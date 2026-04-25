# SPDX-License-Identifier: CC0-1.0
# This work has been dedicated to the public domain under the Creative Commons
# Zero v1.0 Universal license. To the extent possible under law, the author(s)
# have waived all copyright and related rights to this work.
# https://creativecommons.org/publicdomain/zero/1.0/

"""
recognition/engine.py — handwriting recognition via Google Handwriting API.

The Google Inputtools API accepts raw stroke coordinates (X/Y lists) and
returns recognised text. This is far more accurate than Tesseract on
handwriting because:
  - It was trained specifically on handwritten ink
  - It receives vector strokes, not a rasterised image
  - It handles multi-word, multi-line, cursive, and 50+ languages natively
  - No local installation required

API endpoint (same one used by Google's demo page — no key needed):
  POST https://inputtools.google.com/request?itc=<lang>-t-i0-handwrit&app=demopage

Fallback: if the network request fails, falls back to Tesseract (if installed).

Language codes: use BCP-47 short codes matching Google's inputtools:
  en, de, fr, es, it, pt, nl, ru, zh-CN, ja, ar, ...
  These differ from Tesseract codes (eng, deu, fra...) — see config.yaml.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from gi.repository import GLib

from core.state_machine import StateMachine, State

log = logging.getLogger(__name__)

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False
    log.warning(
        "requests not installed — Google API unavailable.\n"
        "Install: pip install requests"
    )

try:
    import pytesseract
    from PIL import Image, ImageFilter, ImageOps
    _HAS_TESSERACT = True
except ImportError:
    _HAS_TESSERACT = False


_GOOGLE_API = (
    "https://inputtools.google.com/request"
    "?itc={lang}-t-i0-handwrit&app=demopage"
)


class RecognitionEngine:
    _global_result_callback: Optional[Callable[[str], None]] = None
    _active_surface  = None   # cairo.ImageSurface  (Tesseract fallback)
    _active_strokes  = None   # list[Stroke]         (Google API primary)
    _active_cfg      = None   # Config

    @classmethod
    def run_async(
        cls,
        sm: StateMachine,
        canvas_surface=None,
        language: str = "en",
        result_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        effective_cb = result_callback or cls._global_result_callback
        # Capture current state at call time so the worker thread reads a
        # consistent snapshot even if the canvas is cleared or updated while
        # the OCR request is in flight.
        strokes = cls._active_strokes
        cfg     = cls._active_cfg
        surface = cls._active_surface if canvas_surface is None else canvas_surface
        threading.Thread(
            target=cls._worker,
            args=(sm, language, effective_cb, strokes, cfg, surface),
            daemon=True,
        ).start()

    # ------------------------------------------------------------------ #

    @classmethod
    def _worker(cls, sm, language, result_callback, strokes, cfg, surface) -> None:
        result = ""
        try:
            engine = "google"
            if cfg is not None:
                engine = getattr(cfg.recognition, "engine", "google")

            if engine == "myscript" and strokes and _HAS_REQUESTS:
                result = cls._myscript_api(strokes, cfg, language)
            elif strokes and _HAS_REQUESTS:
                result = cls._google_api(strokes, cfg, language)
            elif surface is not None and _HAS_TESSERACT:
                log.info("[OCR] Falling back to Tesseract")
                result = cls._tesseract(surface, language)
            elif not _HAS_REQUESTS:
                result = "[requests not installed — pip install requests]"
            else:
                result = "[Nothing to recognise]"
        except Exception:
            log.exception("[OCR] Recognition failed")
            result = "[OCR error — check logs]"
        finally:
            GLib.idle_add(cls._finish, sm, result, result_callback)

    # ------------------------------------------------------------------ #
    # Google Handwriting API
    # ------------------------------------------------------------------ #

    @classmethod
    def _google_api(cls, strokes, cfg, language: str) -> str:
        """
        Convert Stroke objects to the API's ink format and POST.

        Each stroke becomes [xs, ys] where xs and ys are plain Python lists
        of floats. The writing_guide width/height tells the API the canvas
        dimensions so it can interpret spatial relationships correctly.
        """
        # Convert Stroke objects → [[x0,x1,...], [y0,y1,...]]
        ink = []
        for stroke in strokes:
            if len(stroke.points) < 2:
                continue
            xs = [float(p[0]) for p in stroke.points]
            ys = [float(p[1]) for p in stroke.points]
            ink.append([xs, ys])

        if not ink:
            return ""

        # Use actual canvas dimensions from the last snapshot allocation.
        # Falls back to 1920x1200 if not yet available.
        alloc = getattr(cls._active_cfg, '_canvas_alloc', None)
        width  = alloc[0] if alloc else 1920
        height = alloc[1] if alloc else 1200

        payload = {
            "app_version": 0.4,
            "api_level":   "5.37.3",
            "device":      "5.0",
            "input_type":  0,
            "options":     "enable_pre_space",
            "requests": [{
                "writing_guide": {
                    "width":  width,
                    "height": height,
                },
                "ink":      ink,
                "language": language,
            }]
        }

        log.info("[OCR] Google API: %d strokes, language=%s", len(ink), language)
        r = _requests.post(
            _GOOGLE_API.format(lang=language),
            json=payload,
            timeout=8,
        )
        r.raise_for_status()

        # Response structure: [status, [[lang, [candidate0, candidate1, ...]]]]
        data = r.json()

        # Validate response structure before indexing — guards against API
        # changes, error responses, or unexpected payloads
        if not (
            isinstance(data, list) and len(data) > 1
            and isinstance(data[1], list) and data[1]
            and isinstance(data[1][0], list) and len(data[1][0]) > 1
            and isinstance(data[1][0][1], list) and data[1][0][1]
            and isinstance(data[1][0][1][0], str)
        ):
            raise ValueError(f"Unexpected Google API response structure: {data!r}")

        text = data[1][0][1][0]
        log.info("[OCR] Google API result: %d chars", len(text))
        log.debug("[OCR] Google API result: %r", text)
        return text

    # ------------------------------------------------------------------ #
    # MyScript Cloud REST API
    # ------------------------------------------------------------------ #

    @classmethod
    def _myscript_api(cls, strokes, cfg, language: str) -> str:
        """
        POST stroke vectors to the MyScript Cloud batch endpoint.

        Docs: https://developer.myscript.com/docs/interactive-ink/3.1/web/rest/
        Endpoint: POST https://cloud.myscript.com/api/v4.0/iink/batch
        Auth: applicationKey header + HMAC-SHA512 signature over the body.
        """
        import hmac as _hmac
        import hashlib
        import json as _json

        ms_cfg = cfg.myscript
        if not ms_cfg.application_key or not ms_cfg.hmac_key:
            raise ValueError(
                "MyScript API requires application_key and hmac_key in config.yaml "
                "under the 'myscript:' section. "
                "Get free credentials at https://developer.myscript.com/"
            )

        alloc = getattr(cfg, "_canvas_alloc", None)
        width  = alloc[0] if alloc else 1920
        height = alloc[1] if alloc else 1200

        # Build MyScript stroke list; generate synthetic 10ms timestamps
        ms_strokes = []
        for stroke in strokes:
            if len(stroke.points) < 2:
                continue
            xs = [float(p[0]) for p in stroke.points]
            ys = [float(p[1]) for p in stroke.points]
            ts = [i * 10 for i in range(len(stroke.points))]
            ms_strokes.append({"x": xs, "y": ys, "t": ts})

        if not ms_strokes:
            return ""

        ms_lang = _GOOGLE_TO_MYSCRIPT.get(language, language)

        payload = {
            "xDPI": 96,
            "yDPI": 96,
            "contentType": "Text",
            "height": height,
            "width": width,
            "strokeGroups": [{"strokes": ms_strokes}],
            "language": ms_lang,
        }

        body_bytes = _json.dumps(payload).encode("utf-8")
        key = (ms_cfg.application_key + ms_cfg.hmac_key).encode("utf-8")
        hmac_val = _hmac.new(key, body_bytes, hashlib.sha512).hexdigest()

        headers = {
            "applicationKey": ms_cfg.application_key,
            "hmac": hmac_val,
            "Content-Type": "application/json",
            # MyScript batch endpoint returns JIIX (application/vnd.myscript.jiix),
            # a JSON-based format — requesting plain application/json causes 406.
            "Accept": "application/vnd.myscript.jiix",
        }

        log.info("[OCR] MyScript API: %d strokes, language=%s", len(ms_strokes), ms_lang)
        r = _requests.post(
            "https://cloud.myscript.com/api/v4.0/iink/batch",
            data=body_bytes,
            headers=headers,
            timeout=8,
        )
        r.raise_for_status()

        # JIIX response: {"type": "Text", "label": "recognised text", "words": [...]}
        data = r.json()
        try:
            text = data["label"]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"Unexpected MyScript JIIX response: {data!r}") from exc

        log.info("[OCR] MyScript API result: %d chars", len(text))
        log.debug("[OCR] MyScript API result: %r", text)
        return text

    # ------------------------------------------------------------------ #
    # Tesseract fallback
    # ------------------------------------------------------------------ #

    @classmethod
    def _tesseract(cls, surface, language: str) -> str:
        # Map Google-style codes to Tesseract codes if needed
        tess_lang = _GOOGLE_TO_TESSERACT.get(language, language)
        img = cls._surface_to_pil(surface)
        img = cls._preprocess(img)
        return pytesseract.image_to_string(
            img, lang=tess_lang, config="--psm 6"
        ).strip()

    @staticmethod
    def _surface_to_pil(surface):
        from PIL import Image
        w, h = surface.get_width(), surface.get_height()
        return Image.frombytes("RGBA", (w, h), bytes(surface.get_data()), "raw", "BGRA")

    @staticmethod
    def _preprocess(img):
        from PIL import ImageFilter, ImageOps
        gray = ImageOps.grayscale(img)
        inv  = ImageOps.invert(gray)
        w, h = inv.size
        if h < 60:
            scale = max(2, 60 // h)
            inv = inv.resize((w * scale, h * scale), resample=3)
        return inv.filter(ImageFilter.SHARPEN)

    # ------------------------------------------------------------------ #

    @classmethod
    def _finish(cls, sm, result, callback) -> bool:
        if callback:
            try:
                callback(result)
            except Exception:
                log.exception("result_callback raised")
        sm.transition(State.IDLE)
        return GLib.SOURCE_REMOVE


# Google BCP-47 → MyScript language code mapping
_GOOGLE_TO_MYSCRIPT = {
    "en":    "en_US",
    "de":    "de_DE",
    "fr":    "fr_FR",
    "es":    "es_ES",
    "it":    "it_IT",
    "pt":    "pt_BR",
    "nl":    "nl_NL",
    "ru":    "ru_RU",
    "zh-CN": "zh_CN",
    "ja":    "ja_JP",
    "ar":    "ar_AE",
}

# Google BCP-47 → Tesseract language code mapping (for fallback)
_GOOGLE_TO_TESSERACT = {
    "en":    "eng",
    "de":    "deu",
    "fr":    "fra",
    "es":    "spa",
    "it":    "ita",
    "pt":    "por",
    "nl":    "nld",
    "ru":    "rus",
    "zh-CN": "chi_sim",
    "ja":    "jpn",
    "ar":    "ara",
}
