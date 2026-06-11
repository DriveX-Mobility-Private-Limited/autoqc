import base64
import json
import tempfile
from pathlib import Path
from typing import Any, Literal, TypedDict

from google.genai import types
from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph
import pillow_avif  # noqa: F401
from pillow_heif import register_heif_opener
from PIL import Image
from PIL import ImageOps
from pydantic import BaseModel, Field

from logger import get_logger
from qc.clients.gemini_client import DownloadedImage
from qc.clients.gemini_client import GeminiClient
from qc.constants.constants import AUTO_QC_GEMINI_MODEL_NAME
from qc.constants.constants import AUTO_QC_GEMINI_IMAGE_EDIT_MODEL_NAME

logging = get_logger()
register_heif_opener()

MAX_CLEANUP_RETRIES = 1
MIN_SAFE_EDIT_CONFIDENCE = 0.75

VIEW_REFERENCE_URLS = {
    "front": "https://ik.imagekit.io/drivex/ik_self_inspection/front_view.avif",
    "right": "https://ik.imagekit.io/drivex/ik_self_inspection/right_view.avif",
    "left": "https://ik.imagekit.io/drivex/ik_self_inspection/left_view.avif",
    "rear": "https://ik.imagekit.io/drivex/ik_self_inspection/rear_view.avif",
}

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
  "confidence": 0.95,
  "can_safely_edit": true,
  "unsafe_reason": "",
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
- confidence is your confidence that the primary two-wheeler and required
  cleanup/fixes are correctly understood.
- can_safely_edit is false when the image is too ambiguous, the requested angle
  would require inventing hidden vehicle sides/parts, the vehicle is too cropped
  to preserve identity, or the primary subject may not be a two-wheeler.
- should_edit is true only when has_primary_two_wheeler is true and either
  cleanup_needed, framing_fix_needed, orientation_fix_needed, or
  angle_fix_needed is true, and can_safely_edit is true.
- If there is no primary two-wheeler, set should_edit false. Do not ask for any
  image edit.
- If uncertain, set confidence below 0.75, can_safely_edit false, and
  should_edit false.
""".strip()

CLEANUP_PROMPT_TEMPLATE = """
Edit this vehicle inspection image using the analysis below.

Analysis JSON:
{analysis_json}

Retry feedback from verifier:
{retry_feedback}

Remove all people, humans, body parts, bags, personal items, clutter, other
vehicles, and any foreground/background distractions that are not part of the
primary two-wheeler.

When a reference view image is provided, use it only as a guide for expected
inspection framing and viewpoint for that angle. Do not copy its vehicle, color,
parts, background, lighting, decals, or license details. The output must remain
the same real two-wheeler from the input image.

If framing_fix_needed is true, put the primary two-wheeler cleanly in frame by
adding realistic surrounding background or gently reframing the image. Keep the
same real-world inspection-photo look. Do not create a studio photo, do not
beautify the vehicle, and do not make the result look AI-generated.

If orientation_fix_needed is true, the provided input image has already been
rotated upright before this edit request. Keep it upright and do not rotate it
back sideways.

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

If the requested cleanup cannot be done without hallucinating vehicle parts,
changing identity, or making the result look synthetic, return the safest
minimal edit instead of forcing the requested angle.

Return only the edited image.
""".strip()

FINAL_ORIENTATION_PROMPT = """
Analyze this edited vehicle inspection image.

Return strict JSON only:
{
  "orientation_fix_needed": false,
  "rotation_angle": 0,
  "reason": "Image is upright for natural inspection viewing."
}

Rules:
- orientation_fix_needed is true when the whole image is sideways, upside down,
  or not upright for natural human inspection viewing.
- rotation_angle must be 0, 90, 180, or 270 and represents the anti-clockwise
  correction needed to make the image upright.
- Do not judge camera perspective or side angle here. Only judge whether the
  returned image needs a whole-image rotation before API response.
""".strip()

CLEANUP_VERIFICATION_PROMPT = """
Verify whether the edited vehicle inspection image is safe to return.

You will receive the original/prepared image first and the edited image second.
Return strict JSON only:
{
  "accepted": true,
  "retry_recommended": false,
  "confidence": 0.95,
  "preserves_primary_vehicle_identity": true,
  "no_hallucinated_vehicle_parts": true,
  "upright": true,
  "in_frame": true,
  "target_view_supported": true,
  "looks_real": true,
  "issues": [],
  "retry_feedback": ""
}

Rules:
- Reject if the primary two-wheeler identity, color, shape, registration plate,
  odometer/details, decals, visible damage, or important parts changed.
- Reject if hidden vehicle sides/parts were invented, left/right was flipped, or
  the output looks synthetic/beautified.
- Reject if the image is still sideways/upside down.
- Reject if the target view was forced even though the source view did not
  support it.
- Accept minor natural background fills and cleanup of non-primary objects.
- If unsure, set accepted false, confidence below 0.75, and retry_recommended
  false so the system does not return a hallucinated edit.
- retry_recommended should be true only when the issue is likely fixable by a
  stricter second edit without changing vehicle identity.
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
    confidence: float = Field(default=0)
    can_safely_edit: bool = Field(default=False)
    unsafe_reason: str = Field(default="")
    should_edit: bool = Field(default=False)
    reason: str = Field(default="")


class FinalOrientationAnalysis(BaseModel):
    orientation_fix_needed: bool = Field(default=False)
    rotation_angle: int = Field(default=0)
    reason: str = Field(default="")


class CleanupVerification(BaseModel):
    accepted: bool = Field(default=False)
    retry_recommended: bool = Field(default=False)
    confidence: float = Field(default=0)
    preserves_primary_vehicle_identity: bool = Field(default=False)
    no_hallucinated_vehicle_parts: bool = Field(default=False)
    upright: bool = Field(default=False)
    in_frame: bool = Field(default=False)
    target_view_supported: bool = Field(default=False)
    looks_real: bool = Field(default=False)
    issues: list[str] = Field(default_factory=list)
    retry_feedback: str = Field(default="")


class CleanupPipelineState(TypedDict, total=False):
    image_url: str
    target_angle: str
    source_image: DownloadedImage
    edit_image: DownloadedImage
    reference_image: DownloadedImage
    analysis: CleanupImageAnalysis
    edited_image: dict[str, Any]
    token_usage: dict[str, Any]
    final_orientation_analysis: dict[str, Any] | None
    verification: CleanupVerification
    retry_count: int
    retry_requested: bool
    retry_feedback: str
    skip_reason: str
    result: dict[str, Any] | None
    error: str
    temp_files: list[str]


PipelineRoute = Literal["skip", "prepare"]
VerificationRoute = Literal["retry", "finalize"]


class NanoBananaClient(GeminiClient):
    def __init__(
        self,
        model_name: str = AUTO_QC_GEMINI_IMAGE_EDIT_MODEL_NAME,
        analysis_model_name: str = AUTO_QC_GEMINI_MODEL_NAME,
    ):
        super().__init__(model_name=model_name)
        self.analysis_model_name = analysis_model_name
        self._cleanup_graph = self._build_cleanup_graph()

    def cleanup_image(
        self,
        image_url: str,
        target_angle: str = "",
    ) -> dict | None:
        logging.bind(
            image_url=image_url,
            target_angle=target_angle,
            edit_model=self.model_name,
            analysis_model=self.analysis_model_name,
        ).info("Image cleanup pipeline started")
        state: CleanupPipelineState = {
            "image_url": image_url,
            "target_angle": target_angle,
            "retry_count": 0,
            "retry_requested": False,
            "retry_feedback": "",
            "temp_files": [],
        }
        final_state = state
        try:
            final_state = self._cleanup_graph.invoke(state)
            return final_state.get("result")
        except Exception:
            logging.exception("Nano Banana image cleanup failed")
            return None
        finally:
            self._delete_pipeline_files(final_state)

    def _build_cleanup_graph(self):
        graph = StateGraph(CleanupPipelineState)
        graph.add_node("download", self._download_cleanup_image_node)
        graph.add_node("analyze", self._analyze_cleanup_image_node)
        graph.add_node("safety_gate", self._safety_gate_cleanup_image_node)
        graph.add_node("prepare", self._prepare_cleanup_image_node)
        graph.add_node("reference", self._prepare_reference_image_node)
        graph.add_node("edit", self._edit_cleanup_image_node)
        graph.add_node(
            "orientation_check",
            self._orientation_check_cleanup_image_node,
        )
        graph.add_node("verify", self._verify_cleanup_image_node)
        graph.add_node("finalize", self._finalize_cleanup_image_node)
        graph.add_node("skip", self._skip_cleanup_image_node)

        graph.add_edge(START, "download")
        graph.add_edge("download", "analyze")
        graph.add_conditional_edges(
            "safety_gate",
            self._route_after_safety_gate,
            {"skip": "skip", "prepare": "prepare"},
        )
        graph.add_edge("analyze", "safety_gate")
        graph.add_edge("prepare", "reference")
        graph.add_edge("reference", "edit")
        graph.add_edge("edit", "orientation_check")
        graph.add_edge("orientation_check", "verify")
        graph.add_conditional_edges(
            "verify",
            self._route_after_verification,
            {"retry": "edit", "finalize": "finalize"},
        )
        graph.add_edge("skip", END)
        graph.add_edge("finalize", END)
        return graph.compile()

    def _download_cleanup_image_node(
        self,
        state: CleanupPipelineState,
    ) -> CleanupPipelineState:
        image = self._download_image(state["image_url"])
        self._track_temp_file(state, image.file_path)
        logging.bind(
            image_url=state["image_url"],
            file_path=image.file_path,
            size_bytes=image.size_bytes,
            mime_type=image.mime_type,
        ).info("Image cleanup source downloaded")
        return {
            "source_image": image,
            "edit_image": image,
            "temp_files": state["temp_files"],
        }

    def _analyze_cleanup_image_node(
        self,
        state: CleanupPipelineState,
    ) -> CleanupPipelineState:
        image = state["source_image"]
        analysis = self._analyze_image(
            image,
            target_angle=state.get("target_angle", ""),
        )
        if not analysis:
            logging.bind(image_url=state["image_url"]).error(
                "Image cleanup stopped because analysis failed",
            )
            return {"error": "analysis_failed"}
        return {"analysis": analysis}

    def _safety_gate_cleanup_image_node(
        self,
        state: CleanupPipelineState,
    ) -> CleanupPipelineState:
        analysis = state.get("analysis")
        if not analysis:
            return {"skip_reason": "Image cleanup analysis failed"}

        if self._should_skip_cleanup(analysis):
            skip_reason = (
                analysis.unsafe_reason
                or analysis.reason
                or "Image cleanup skipped by safety analysis"
            )
            logging.bind(
                image_url=state["image_url"],
                target_angle=state.get("target_angle", ""),
                cleanup_analysis=analysis.model_dump(),
                skip_reason=skip_reason,
            ).info("Image cleanup safety gate blocked edit")
            return {"skip_reason": skip_reason}

        logging.bind(
            image_url=state["image_url"],
            target_angle=state.get("target_angle", ""),
            cleanup_analysis=analysis.model_dump(),
        ).info("Image cleanup safety gate allowed edit")
        return {"skip_reason": ""}

    @staticmethod
    def _route_after_safety_gate(state: CleanupPipelineState) -> PipelineRoute:
        if state.get("error") or state.get("skip_reason"):
            return "skip"
        return "prepare"

    def _prepare_cleanup_image_node(
        self,
        state: CleanupPipelineState,
    ) -> CleanupPipelineState:
        analysis = state["analysis"]
        image = state["source_image"]
        edit_image = self._prepare_edit_image(image, analysis)
        if edit_image.file_path != image.file_path:
            self._track_temp_file(state, edit_image.file_path)

        logging.bind(
            image_url=state["image_url"],
            target_angle=state.get("target_angle", ""),
            cleanup_analysis=analysis.model_dump(),
            edit_file_path=edit_image.file_path,
            edit_size_bytes=edit_image.size_bytes,
            edit_mime_type=edit_image.mime_type,
        ).info("Image cleanup edit request prepared")
        return {"edit_image": edit_image, "temp_files": state["temp_files"]}

    def _prepare_reference_image_node(
        self,
        state: CleanupPipelineState,
    ) -> CleanupPipelineState:
        analysis = state["analysis"]
        reference_image = self._download_reference_image(analysis.target_view_label)
        if not reference_image:
            logging.bind(
                image_url=state["image_url"],
                target_view_label=analysis.target_view_label,
            ).info("Image cleanup reference image not available")
            return {}

        self._track_temp_file(state, reference_image.file_path)
        logging.bind(
            image_url=state["image_url"],
            target_view_label=analysis.target_view_label,
            reference_file_path=reference_image.file_path,
            reference_size_bytes=reference_image.size_bytes,
            reference_mime_type=reference_image.mime_type,
        ).info("Image cleanup reference image prepared")
        return {
            "reference_image": reference_image,
            "temp_files": state["temp_files"],
        }

    def _edit_cleanup_image_node(
        self,
        state: CleanupPipelineState,
    ) -> CleanupPipelineState:
        analysis = state["analysis"]
        edit_image = state["edit_image"]
        reference_image = state.get("reference_image")

        contents = [
            self._build_cleanup_prompt(
                analysis,
                retry_feedback=state.get("retry_feedback", ""),
            ),
            "Input vehicle inspection image:",
            types.Part.from_bytes(
                data=Path(edit_image.file_path).read_bytes(),
                mime_type=edit_image.mime_type,
            ),
        ]
        if reference_image:
            contents.extend(
                [
                    f"Reference {analysis.target_view_label} inspection view "
                    "for framing and camera angle only:",
                    types.Part.from_bytes(
                        data=Path(reference_image.file_path).read_bytes(),
                        mime_type=reference_image.mime_type,
                    ),
                ],
            )

        logging.bind(
            image_url=state["image_url"],
            target_angle=state.get("target_angle", ""),
            retry_count=state.get("retry_count", 0),
            has_reference_image=bool(reference_image),
            model=self.model_name,
        ).info("Image cleanup edit request started")
        response = self._client().models.generate_content(
            model=self.model_name,
            contents=contents,
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )
        edited_image = self._extract_image(response)
        if not edited_image:
            logging.bind(
                image_url=state["image_url"],
                target_angle=state.get("target_angle", ""),
                model=self.model_name,
            ).error("Image cleanup edit response did not include an image")
            return {"error": "edit_response_missing_image"}

        token_usage = self._get_token_usage(response)
        logging.info(f"Nano Banana token usage: {token_usage}")
        return {
            "edited_image": edited_image,
            "token_usage": token_usage,
            "temp_files": state["temp_files"],
        }

    def _orientation_check_cleanup_image_node(
        self,
        state: CleanupPipelineState,
    ) -> CleanupPipelineState:
        if state.get("error"):
            return {}

        final_orientation_analysis = self._fix_edited_image_orientation(
            state["edited_image"],
            state["analysis"],
        )
        return {
            "final_orientation_analysis": final_orientation_analysis,
        }

    def _verify_cleanup_image_node(
        self,
        state: CleanupPipelineState,
    ) -> CleanupPipelineState:
        if state.get("error"):
            return {}

        verification = self._verify_cleanup_image(
            original_image=state["edit_image"],
            edited_image=state["edited_image"],
            analysis=state["analysis"],
        )
        if not verification:
            return {"error": "verification_failed"}

        retry_count = state.get("retry_count", 0)
        next_state: CleanupPipelineState = {
            "verification": verification,
            "retry_requested": False,
        }
        if (
            not verification.accepted
            and verification.retry_recommended
            and retry_count < MAX_CLEANUP_RETRIES
        ):
            next_state["retry_count"] = retry_count + 1
            next_state["retry_requested"] = True
            next_state["retry_feedback"] = verification.retry_feedback
            logging.bind(
                image_url=state["image_url"],
                retry_count=retry_count + 1,
                cleanup_verification=verification.model_dump(),
            ).warning("Image cleanup verifier requested one retry")
        return next_state

    def _route_after_verification(
        self,
        state: CleanupPipelineState,
    ) -> VerificationRoute:
        if not state.get("error") and state.get("retry_requested"):
            return "retry"
        return "finalize"

    def _skip_cleanup_image_node(
        self,
        state: CleanupPipelineState,
    ) -> CleanupPipelineState:
        analysis = state.get("analysis")
        reason = state.get("skip_reason") or state.get("error", "cleanup_not_needed")
        return {
            "result": {
                "skipped": True,
                "skip_reason": reason,
                "cleanup_analysis": analysis.model_dump() if analysis else None,
                "model": self.analysis_model_name,
            },
        }

    def _finalize_cleanup_image_node(
        self,
        state: CleanupPipelineState,
    ) -> CleanupPipelineState:
        analysis = state.get("analysis")
        verification = state.get("verification")
        if state.get("error") or not state.get("edited_image"):
            return {
                "result": {
                    "skipped": True,
                    "skip_reason": (
                        "Cleanup failed validation; original image left unchanged"
                    ),
                    "cleanup_analysis": analysis.model_dump() if analysis else None,
                    "cleanup_verification": (
                        verification.model_dump() if verification else None
                    ),
                    "model": self.model_name,
                },
            }

        if not verification or not verification.accepted:
            return {
                "result": {
                    "skipped": True,
                    "skip_reason": (
                        "Cleanup result failed verification; original image left "
                        "unchanged"
                    ),
                    "cleanup_analysis": analysis.model_dump() if analysis else None,
                    "cleanup_verification": (
                        verification.model_dump() if verification else None
                    ),
                    "final_orientation_analysis": state.get(
                        "final_orientation_analysis",
                    ),
                    "model": self.model_name,
                    "token_usage": state.get("token_usage"),
                },
            }

        logging.bind(
            image_url=state["image_url"],
            target_angle=state.get("target_angle", ""),
            model=self.model_name,
            token_usage=state.get("token_usage"),
            final_orientation_analysis=state.get("final_orientation_analysis"),
            cleanup_verification=verification.model_dump(),
        ).info("Image cleanup pipeline completed")
        return {
            "result": {
                **state["edited_image"],
                "skipped": False,
                "cleanup_analysis": analysis.model_dump() if analysis else None,
                "cleanup_verification": verification.model_dump(),
                "final_orientation_analysis": state.get(
                    "final_orientation_analysis",
                ),
                "model": self.model_name,
                "token_usage": state.get("token_usage"),
            },
        }

    @staticmethod
    def _should_skip_cleanup(analysis: CleanupImageAnalysis) -> bool:
        return (
            not analysis.has_primary_two_wheeler
            or not analysis.should_edit
            or not analysis.can_safely_edit
            or analysis.confidence < MIN_SAFE_EDIT_CONFIDENCE
        )

    def _verify_cleanup_image(
        self,
        original_image: DownloadedImage,
        edited_image: dict[str, Any],
        analysis: CleanupImageAnalysis,
    ) -> CleanupVerification | None:
        edited_download = self._data_url_to_downloaded_image(
            edited_image["data_url"],
            edited_image["mime_type"],
        )
        try:
            logging.bind(
                original_file_path=original_image.file_path,
                edited_file_path=edited_download.file_path,
                target_view_label=analysis.target_view_label,
                model=self.analysis_model_name,
            ).info("Image cleanup verification started")
            response = self._client().models.generate_content(
                model=self.analysis_model_name,
                contents=[
                    self._build_verification_prompt(analysis),
                    "Original/prepared vehicle inspection image:",
                    types.Part.from_bytes(
                        data=Path(original_image.file_path).read_bytes(),
                        mime_type=original_image.mime_type,
                    ),
                    "Edited vehicle inspection image:",
                    types.Part.from_bytes(
                        data=Path(edited_download.file_path).read_bytes(),
                        mime_type=edited_download.mime_type,
                    ),
                ],
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                ),
            )
            verification = CleanupVerification.model_validate_json(response.text)
            if verification.confidence < MIN_SAFE_EDIT_CONFIDENCE:
                verification.accepted = False
                verification.retry_recommended = False

            logging.bind(
                cleanup_verification=verification.model_dump(),
                model=self.analysis_model_name,
            ).info("Image cleanup verification completed")
            return verification
        except Exception:
            logging.exception("Image cleanup verification failed")
            return None
        finally:
            self._delete_file(edited_download.file_path)

    def _download_reference_image(self, view_label: str) -> DownloadedImage | None:
        reference_url = VIEW_REFERENCE_URLS.get(view_label)
        if not reference_url:
            return None

        downloaded = self._download_image(reference_url)
        try:
            return self._convert_image_to_png(downloaded)
        except Exception:
            logging.exception(
                f"Failed to prepare {view_label} cleanup reference image",
            )
            return None
        finally:
            self._delete_file(downloaded.file_path)

    @staticmethod
    def _convert_image_to_png(image: DownloadedImage) -> DownloadedImage:
        with Image.open(image.file_path) as source:
            converted = ImageOps.exif_transpose(source)
            if converted.mode not in {"RGB", "RGBA"}:
                converted = converted.convert("RGB")

            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_file:
                converted.save(temp_file.name, format="PNG")
                file_path = temp_file.name

        size_bytes = Path(file_path).stat().st_size
        logging.bind(
            source_file_path=image.file_path,
            png_file_path=file_path,
            size_bytes=size_bytes,
        ).info("Converted cleanup reference image to PNG")
        return DownloadedImage(
            file_path=file_path,
            size_bytes=size_bytes,
            mime_type="image/png",
        )

    @staticmethod
    def _track_temp_file(state: CleanupPipelineState, file_path: str) -> None:
        temp_files = state.setdefault("temp_files", [])
        if file_path not in temp_files:
            temp_files.append(file_path)

    def _delete_pipeline_files(self, state: CleanupPipelineState) -> None:
        for file_path in reversed(state.get("temp_files", [])):
            logging.bind(file_path=file_path).info("Deleting cleanup pipeline file")
            self._delete_file(file_path)

    def _analyze_image(
        self,
        image: DownloadedImage,
        target_angle: str = "",
    ) -> CleanupImageAnalysis | None:
        prompt = self._build_analysis_prompt(target_angle)
        try:
            logging.bind(
                file_path=image.file_path,
                size_bytes=image.size_bytes,
                mime_type=image.mime_type,
                target_angle=target_angle,
                model=self.analysis_model_name,
            ).info("Image cleanup analysis request started")
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
            logging.bind(
                cleanup_analysis=analysis.model_dump(),
                model=self.analysis_model_name,
            ).info("Image cleanup analysis completed")
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
    def _build_cleanup_prompt(
        analysis: CleanupImageAnalysis,
        retry_feedback: str = "",
    ) -> str:
        analysis_json = json.dumps(
            analysis.model_dump(),
            ensure_ascii=True,
            sort_keys=True,
        )
        return CLEANUP_PROMPT_TEMPLATE.format(
            analysis_json=analysis_json,
            retry_feedback=retry_feedback or "None",
        )

    @staticmethod
    def _build_verification_prompt(analysis: CleanupImageAnalysis) -> str:
        analysis_json = json.dumps(
            analysis.model_dump(),
            ensure_ascii=True,
            sort_keys=True,
        )
        return (
            f"{CLEANUP_VERIFICATION_PROMPT}\n\n"
            f"Cleanup analysis JSON:\n{analysis_json}\n"
            "Use the target_view_label only to verify that the edit stayed within "
            "what the original image visibly supports."
        )

    def _prepare_edit_image(
        self,
        image: DownloadedImage,
        analysis: CleanupImageAnalysis,
    ) -> DownloadedImage:
        if not analysis.orientation_fix_needed or analysis.rotation_angle == 0:
            logging.bind(
                orientation_fix_needed=analysis.orientation_fix_needed,
                rotation_angle=analysis.rotation_angle,
            ).info("Cleanup image pre-rotation not required")
            return image

        if analysis.rotation_angle not in {90, 180, 270}:
            logging.warning(
                f"Skipping unsupported cleanup rotation: {analysis.rotation_angle}",
            )
            return image

        try:
            logging.bind(
                file_path=image.file_path,
                rotation_angle=analysis.rotation_angle,
            ).info("Rotating cleanup image before edit")
            return self._rotate_image(image, analysis.rotation_angle)
        except Exception:
            logging.exception("Failed to rotate cleanup image before editing")
            return image

    @staticmethod
    def _rotate_image(
        image: DownloadedImage,
        rotation_angle: int,
    ) -> DownloadedImage:
        source_path = Path(image.file_path)
        suffix = source_path.suffix or ".jpg"
        with Image.open(source_path) as source:
            rotated = ImageOps.exif_transpose(source).rotate(
                rotation_angle,
                expand=True,
            )
            if image.mime_type == "image/jpeg" and rotated.mode not in {
                "RGB",
                "L",
            }:
                rotated = rotated.convert("RGB")

            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=suffix,
            ) as temp_file:
                rotated.save(temp_file.name)
                file_path = temp_file.name

        size_bytes = Path(file_path).stat().st_size
        logging.info(
            "Rotated cleanup image before editing: "
            f"angle={rotation_angle}, size={size_bytes}B",
        )
        logging.bind(
            source_file_path=image.file_path,
            rotated_file_path=file_path,
            rotation_angle=rotation_angle,
            size_bytes=size_bytes,
            mime_type=image.mime_type,
        ).info("Cleanup image pre-rotation completed")
        return DownloadedImage(
            file_path=file_path,
            size_bytes=size_bytes,
            mime_type=image.mime_type,
        )

    def _fix_edited_image_orientation(
        self,
        edited_image: dict,
        original_analysis: CleanupImageAnalysis,
    ) -> dict | None:
        if not original_analysis.orientation_fix_needed:
            logging.bind(
                orientation_fix_needed=False,
            ).info("Final cleanup orientation verification not required")
            return None

        image = self._data_url_to_downloaded_image(
            edited_image["data_url"],
            edited_image["mime_type"],
        )
        try:
            final_analysis = self._analyze_final_orientation(image)
            if not final_analysis:
                logging.error("Final cleanup orientation verification failed")
                return None

            final_data = final_analysis.model_dump()
            if (
                not final_analysis.orientation_fix_needed
                or final_analysis.rotation_angle == 0
            ):
                logging.bind(
                    final_orientation_analysis=final_data,
                ).info("Final cleanup orientation already upright")
                return final_data

            if final_analysis.rotation_angle not in {90, 180, 270}:
                logging.warning(
                    "Skipping unsupported final cleanup rotation: "
                    f"{final_analysis.rotation_angle}",
                )
                return final_data

            rotated_image = self._rotate_image(image, final_analysis.rotation_angle)
            try:
                image_bytes = Path(rotated_image.file_path).read_bytes()
                image_base64 = base64.b64encode(image_bytes).decode()
                edited_image["data_url"] = (
                    f"data:{rotated_image.mime_type};base64,{image_base64}"
                )
                edited_image["mime_type"] = rotated_image.mime_type
                final_data["applied_rotation"] = final_analysis.rotation_angle
                logging.bind(
                    final_orientation_analysis=final_data,
                ).info("Final cleanup image rotation applied")
                return final_data
            finally:
                self._delete_file(rotated_image.file_path)
        finally:
            self._delete_file(image.file_path)

    def _analyze_final_orientation(
        self,
        image: DownloadedImage,
    ) -> FinalOrientationAnalysis | None:
        try:
            logging.bind(
                file_path=image.file_path,
                size_bytes=image.size_bytes,
                mime_type=image.mime_type,
                model=self.analysis_model_name,
            ).info("Final cleanup orientation analysis started")
            response = self._client().models.generate_content(
                model=self.analysis_model_name,
                contents=[
                    FINAL_ORIENTATION_PROMPT,
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
            analysis = FinalOrientationAnalysis.model_validate_json(response.text)
            logging.bind(
                final_orientation_analysis=analysis.model_dump(),
                model=self.analysis_model_name,
            ).info("Final cleanup orientation analysis completed")
            return analysis
        except Exception:
            logging.exception("Final cleanup orientation analysis failed")
            return None

    @staticmethod
    def _data_url_to_downloaded_image(
        data_url: str,
        mime_type: str,
    ) -> DownloadedImage:
        _, image_base64 = data_url.split(",", 1)
        suffix = ".png" if mime_type == "image/png" else ".jpg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            image_bytes = base64.b64decode(image_base64)
            temp_file.write(image_bytes)
            file_path = temp_file.name

        logging.bind(
            file_path=file_path,
            size_bytes=len(image_bytes),
            mime_type=mime_type,
        ).info("Converted edited cleanup data URL to temporary image")
        return DownloadedImage(
            file_path=file_path,
            size_bytes=len(image_bytes),
            mime_type=mime_type,
        )

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
