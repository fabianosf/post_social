"""
Postay — Vision Service (Fase 8)
Análise visual de imagens e vídeos via OpenAI Vision + Pillow fallback.
Suporta: OpenAI gpt-4o-mini Vision (detail:low) | Pillow básico sem chave.
"""

import base64
import io
import json
import logging
import os
import subprocess
import tempfile
import time

logger = logging.getLogger(__name__)

_AI_PROVIDER = os.environ.get("AI_PROVIDER", "openai")


def is_vision_available() -> bool:
    """True apenas se OpenAI Vision está configurado (Groq não suporta visão)."""
    return _AI_PROVIDER == "openai" and bool(os.environ.get("OPENAI_API_KEY"))


def _prepare_image_b64(path: str, max_size: int = 1024) -> str | None:
    """Redimensiona para max_size px e retorna string base64 JPEG."""
    try:
        from PIL import Image
        img = Image.open(path).convert("RGB")
        img.thumbnail((max_size, max_size), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        logger.warning(f"_prepare_image_b64 falhou: {e}")
        return None


def _vision_chat(b64: str, prompt: str, max_tokens: int = 900) -> dict | None:
    """Envia imagem base64 ao GPT-4o-mini Vision. Retorna dict JSON ou None."""
    try:
        from openai import OpenAI
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            return None
        cl = OpenAI(api_key=key)
        for attempt in range(3):
            try:
                resp = cl.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{b64}",
                                    "detail": "low",
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }],
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )
                return json.loads(resp.choices[0].message.content)
            except Exception as e:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    logger.warning(f"_vision_chat falhou: {e}")
                    return None
    except ImportError:
        return None


def _basic_analysis(path: str) -> dict:
    """
    Fallback Pillow: brightness, contrast, aspect ratio e dominant color.
    Retorna dict compatível com o retorno do Vision AI.
    """
    try:
        from PIL import Image, ImageStat
        img = Image.open(path).convert("RGB")
        w, h = img.size
        aspect = round(w / h, 2)
        stat = ImageStat.Stat(img)
        brightness = round(sum(stat.mean) / 3 / 255, 2)
        stddev = round(sum(stat.stddev) / 3 / 255, 2)

        small = img.resize((3, 3))
        center_pixel = small.getpixel((1, 1))
        dominant = "#{:02x}{:02x}{:02x}".format(*center_pixel)

        brightness_score = max(0.0, 10 - abs(brightness - 0.55) * 20)
        contrast_score = min(stddev * 30, 10.0)
        aspect_score = 10.0 if 0.5 <= aspect <= 1.0 else (7.0 if aspect <= 1.8 else 5.0)
        score = round(brightness_score * 0.4 + contrast_score * 0.35 + aspect_score * 0.25, 1)
        score = max(1.0, min(10.0, score))

        recs = [
            f"Brilho: {'adequado' if 0.35 <= brightness <= 0.75 else 'ajuste o brilho da imagem'}",
            f"Contraste: {'bom' if stddev > 0.15 else 'aumente o contraste para destacar elementos'}",
            f"Proporção: {'ideal para Reels (9:16)' if 0.5 <= aspect <= 0.6 else ('adequada' if aspect <= 1.0 else 'prefira formato vertical para mais alcance')}",
        ]

        return {
            "overall_score": score,
            "face_detected": False,
            "has_text": False,
            "hook_visual": "Análise básica — Vision IA não disponível",
            "dominant_color": dominant,
            "brightness": brightness,
            "contrast": stddev,
            "aspect_ratio": aspect,
            "retention_prediction": round(score / 10 * 60, 1),
            "thumbnail_score": score,
            "ctr_prediction": "baixo" if score < 5 else ("médio" if score < 7.5 else "alto"),
            "emotion_detected": "neutro",
            "visual_elements": ["análise Pillow — sem detecção de objetos"],
            "recommendations": recs,
            "improvements": ["Configure OPENAI_API_KEY para análise visual completa com IA"],
            "is_fallback": True,
        }
    except Exception as e:
        logger.warning(f"_basic_analysis falhou: {e}")
        return {
            "overall_score": 5.0,
            "face_detected": False,
            "has_text": False,
            "hook_visual": "Não disponível",
            "retention_prediction": 30.0,
            "thumbnail_score": 5.0,
            "ctr_prediction": "médio",
            "recommendations": ["Não foi possível analisar a imagem"],
            "improvements": ["Verifique se o arquivo é uma imagem válida"],
            "is_fallback": True,
        }


def analyze_image(path: str, niche: str = "geral") -> dict | None:
    """
    Análise completa de imagem para Instagram.
    Usa Vision AI se disponível, senão Pillow.
    """
    if not os.path.exists(path):
        return None

    if not is_vision_available():
        return _basic_analysis(path)

    b64 = _prepare_image_b64(path)
    if not b64:
        return _basic_analysis(path)

    prompt = (
        f"Analise esta imagem para uso no Instagram (nicho: {niche}). "
        "Retorne JSON com os campos: "
        "overall_score (int 1-10), "
        "face_detected (bool), "
        "has_text (bool), "
        "hook_visual (string: elemento visual que mais prende atenção), "
        "emotion_detected (string: emoção principal transmitida), "
        "dominant_color (string hex como #ff5500), "
        "retention_prediction (float: % de retenção estimada em Reels, 0-100), "
        "thumbnail_score (int 1-10), "
        "ctr_prediction (string: baixo|médio|alto), "
        "visual_elements (list de strings: elementos visuais identificados), "
        "recommendations (list de 3-5 strings: recomendações para melhorar CTR), "
        "improvements (list de strings: melhorias específicas para o nicho). "
        "Responda em português brasileiro."
    )
    result = _vision_chat(b64, prompt)
    if result is None:
        return _basic_analysis(path)
    result["is_fallback"] = False
    return result


def analyze_thumbnail(path: str, niche: str = "geral") -> dict | None:
    """
    Análise focada em CTR de thumbnail: legibilidade, emoção, curiosidade.
    """
    if not os.path.exists(path):
        return None

    if not is_vision_available():
        base = _basic_analysis(path)
        base["thumbnail_analysis"] = "Análise básica — Vision IA não disponível"
        return base

    b64 = _prepare_image_b64(path, max_size=512)
    if not b64:
        return _basic_analysis(path)

    prompt = (
        f"Esta é uma thumbnail para Instagram/Reels (nicho: {niche}). "
        "Avalie com foco em CTR (taxa de clique). "
        "Retorne JSON com: "
        "thumbnail_score (int 1-10), "
        "face_detected (bool), "
        "face_expression (string: expressão facial se houver rosto, senão null), "
        "has_text (bool), "
        "text_legibility (string: boa|ruim|ausente), "
        "curiosity_gap (bool: gera curiosidade?), "
        "emotion_triggered (string: emoção que provoca no espectador), "
        "color_contrast (string: alto|médio|baixo), "
        "overall_score (int 1-10), "
        "ctr_prediction (string: baixo|médio|alto), "
        "thumbnail_strengths (list de strings: pontos fortes), "
        "thumbnail_weaknesses (list de strings: pontos fracos), "
        "improvements (list de 3-5 strings: melhorias para aumentar CTR), "
        "recommendations (list de strings). "
        "Responda em português."
    )
    result = _vision_chat(b64, prompt)
    if result is None:
        base = _basic_analysis(path)
        base["thumbnail_analysis"] = "Falha na Vision AI — análise básica aplicada"
        return base
    result["is_fallback"] = False
    return result


def extract_video_frame(video_path: str, time_sec: float = 2.0) -> str | None:
    """
    Extrai frame de vídeo via ffmpeg.
    Retorna caminho do JPEG temporário ou None se ffmpeg indisponível.
    """
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(time_sec),
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "2",
            tmp_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            return tmp_path
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
        logger.warning(f"extract_video_frame falhou: {e}")
        return None


def analyze_video(video_path: str, niche: str = "geral") -> dict | None:
    """
    Analisa vídeo extraindo frame aos 2s e passando para analyze_image.
    """
    if not os.path.exists(video_path):
        return None

    frame_path = extract_video_frame(video_path, time_sec=2.0)

    if frame_path:
        try:
            result = analyze_image(frame_path, niche)
        finally:
            try:
                os.unlink(frame_path)
            except Exception:
                pass
    else:
        result = {
            "overall_score": 5.0,
            "face_detected": False,
            "has_text": False,
            "hook_visual": "Análise de frame não disponível — ffmpeg ausente",
            "retention_prediction": 40.0,
            "thumbnail_score": 5.0,
            "ctr_prediction": "médio",
            "recommendations": [
                "Instale ffmpeg para análise de frame de vídeo",
                "No servidor de produção (Docker) o ffmpeg já está disponível",
            ],
            "improvements": [],
            "is_fallback": True,
            "ffmpeg_unavailable": True,
        }

    if result:
        result["content_type"] = "video"
        result["frame_extracted"] = frame_path is not None
    return result


def ffmpeg_available() -> bool:
    """True se ffmpeg está instalado e acessível."""
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False
