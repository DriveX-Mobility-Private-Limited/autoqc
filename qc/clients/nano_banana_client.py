import base64
import json
from pathlib import Path

from google.genai import types
from pydantic import BaseModel, Field

from logger import get_logger
from qc.clients.gemini_client import DownloadedImage
from qc.clients.gemini_client import GeminiClient
from qc.constants.constants import AUTO_QC_GEMINI_MODEL_NAME
from qc.constants.constants import AUTO_QC_GEMINI_IMAGE_EDIT_MODEL_NAME

logging = get_logger()

CLEANUP_ANALYSIS_PROMPT = """
Analyze this image before vehicle inspection cleanup.

Return strict JSON only:
{
  "has_primary_two_wheeler": true,
  "cleanup_needed": true,
  "framing_fix_needed": false,
  "orientation_fix_needed": false,
  "rotation_angle": 0,
  "angle_fix_needed": false,
  "current_view_label": "right",
  "target_view_label": "right",
  "should_edit": true,
  "reason": "Primary two-wheeler is present and background cleanup is needed."
}

Rules:
- has_primary_two_wheeler is true only when the image contains a clear primary
  scooter, motorcycle, or other two-wheeler intended for inspection.
- cleanup_needed is true when people, body parts, bags, clutter, other vehicles,
  or foreground/background distractions should be removed.
- framing_fix_needed is true when the primary two-wheeler is too close to an
  image edge, cropped, partially out of frame, or surrounded by an awkward crop
  that can be improved with natural background padding/reframing.
- orientation_fix_needed is true when the whole image is sideways, upside down,
  or not upright for natural human inspection viewing. rotation_angle must be
  0, 90, 180, or 270 and represents the anti-clockwise correction needed to make
  the image upright.
- angle_fix_needed is true when the image is tilted, has strong perspective
  skew, or is an oblique 100-140 degree capture that should be normalized toward
  the requested target angle for inspection.
- current_view_label and target_view_label must be one of front, rear, left,
  right, odometer, or other. Use the requested target angle when provided.
- should_edit is true only when has_primary_two_wheeler is true and either
  cleanup_needed, framing_fix_needed, orientation_fix_needed, or
  angle_fix_needed is true.
- If there is no primary two-wheeler, set should_edit false. Do not ask for any
  image edit.
""".strip()

CLEANUP_PROMPT_TEMPLATE = """
Edit this vehicle inspection image using the analysis below.

Analysis JSON:
{analysis_json}

Remove all people, humans, body parts, bags, personal items, clutter, other
vehicles, and any foreground/background distractions that are not part of the
primary two-wheeler.

If framing_fix_needed is true, put the primary two-wheeler cleanly in frame by
adding realistic surrounding background or gently reframing the image. Keep the
same real-world inspection-photo look. Do not create a studio photo, do not
beautify the vehicle, and do not make the result look AI-generated.

If orientation_fix_needed is true, rotate the entire photo by rotation_angle
degrees anti-clockwise so the two-wheeler is upright for natural inspection
viewing. Preserve the image content while rotating, then fill any empty corners
or edges naturally from the surrounding floor/wall/background.

If angle_fix_needed is true, improve the inspection angle by correcting tilt,
perspective skew, and mild oblique capture. When a target angle is requested,
make the image read as that inspection angle only if the visible vehicle side
already supports it. For example, a 120-degree oblique right-side image may be
normalized toward a cleaner right-side inspection view. Do not invent hidden
vehicle surfaces, do not flip left/right, and do not transform a genuinely wrong
view into a different side.

Keep the primary two-wheeler exactly the same: shape, color, registration plate,
odometer/details if visible, lighting direction, camera height/context, shadows,
and image resolution. Do not redraw, replace, flip, upscale, or change the
vehicle. If any part of the primary vehicle is outside the original image, do
not invent missing vehicle details; add only natural background space. Fill
removed areas naturally using the surrounding background so the result looks
like the same real inspection photo.

Return only the edited image.
""".strip()


class CleanupImageAnalysis(BaseModel):
    has_primary_two_wheeler: bool = Field(default=False)
    cleanup_needed: bool = Field(default=False)
    framing_fix_needed: bool = Field(default=False)
    orientation_fix_needed: bool = Field(default=False)
    rotation_angle: int = Field(default=0)
    angle_fix_needed: bool = Field(default=False)
    current_view_label: str = Field(default="other")
    target_view_label: str = Field(default="other")
    should_edit: bool = Field(default=False)
    reason: str = Field(default="")


class NanoBananaClient(GeminiClient):
    def __init__(
        self,
        model_name: str = AUTO_QC_GEMINI_IMAGE_EDIT_MODEL_NAME,
        analysis_model_name: str = AUTO_QC_GEMINI_MODEL_NAME,
    ):
        super().__init__(model_name=model_name)
        self.analysis_model_name = analysis_model_name

    def cleanup_image(
        self,
        image_url: str,
        target_angle: str = "",
    ) -> dict | None:
        image = self._download_image(image_url)
        try:
            analysis = self._analyze_image(image, target_angle=target_angle)
            if not analysis:
                return None

            analysis_data = analysis.model_dump()
            if not analysis.has_primary_two_wheeler or not analysis.should_edit:
                return {
                    "skipped": True,
                    "skip_reason": analysis.reason,
                    "cleanup_analysis": analysis_data,
                    "model": self.analysis_model_name,
                }

            response = self._client().models.generate_content(
                model=self.model_name,
                contents=[
                    self._build_cleanup_prompt(analysis),
                    types.Part.from_bytes(
                        data=Path(image.file_path).read_bytes(),
                        mime_type=image.mime_type,
                    ),
                ],
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                ),
            )
            edited_image = self._extract_image(response)
            if not edited_image:
                return None

            token_usage = self._get_token_usage(response)
            logging.info(f"Nano Banana token usage: {token_usage}")
            return {
                **edited_image,
                "skipped": False,
                "cleanup_analysis": analysis_data,
                "model": self.model_name,
                "token_usage": token_usage,
            }
        except Exception:
            logging.exception("Nano Banana image cleanup failed")
            return None
        finally:
            self._delete_file(image.file_path)

    def _analyze_image(
        self,
        image: DownloadedImage,
        target_angle: str = "",
    ) -> CleanupImageAnalysis | None:
        prompt = self._build_analysis_prompt(target_angle)
        try:
            response = self._client().models.generate_content(
                model=self.analysis_model_name,
                contents=[
                    prompt,
                    types.Part.from_bytes(
                        data=Path(image.file_path).read_bytes(),
                        mime_type=image.mime_type,
                    ),
                ],
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                ),
            )
            analysis = CleanupImageAnalysis.model_validate_json(response.text)
            logging.info(
                "Image cleanup analysis: "
                f"{analysis.model_dump_json(exclude_none=True)}",
            )
            return analysis
        except Exception:
            logging.exception("Image cleanup analysis failed")
            return None

    @staticmethod
    def _build_analysis_prompt(target_angle: str = "") -> str:
        if not target_angle:
            return CLEANUP_ANALYSIS_PROMPT

        return (
            f"{CLEANUP_ANALYSIS_PROMPT}\n\n"
            f"Requested target angle: {target_angle.strip().lower()}\n"
            "Use this as target_view_label when it is one of front, rear, left, "
            "right, odometer, or other."
        )

    @staticmethod
    def _build_cleanup_prompt(analysis: CleanupImageAnalysis) -> str:
        analysis_json = json.dumps(
            analysis.model_dump(),
            ensure_ascii=True,
            sort_keys=True,
        )
        return CLEANUP_PROMPT_TEMPLATE.format(analysis_json=analysis_json)

    def _extract_image(self, response) -> dict | None:
        parts = getattr(response, "parts", None) or []
        if not parts:
            candidates = getattr(response, "candidates", None) or []
            if candidates:
                parts = getattr(candidates[0].content, "parts", None) or []

        for part in parts:
            inline_data = getattr(part, "inline_data", None) or getattr(
                part,
                "inlineData",
                None,
            )
            if not inline_data:
                continue

            image_bytes = inline_data.data
            if isinstance(image_bytes, str):
                image_base64 = image_bytes
            else:
                image_base64 = base64.b64encode(image_bytes).decode()
            mime_type = inline_data.mime_type or "image/png"
            return {
                "data_url": f"data:{mime_type};base64,{image_base64}",
                "mime_type": mime_type,
            }
        return None
