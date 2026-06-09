from pydantic import BaseModel, Field


class LicensePlateResult(BaseModel):
    success: bool = Field()
    license_plate: str | None = Field()
    error: str | None = Field()
    image_index: int = Field()
    view_label: str = Field()
    people_in_background: int = Field(default=0)
    vehicles_in_background: int = Field(default=0)
    confidence: float = Field()
    is_ai_generated: bool = Field()
    is_screenshot: bool = Field(default=False)
    is_rotated: bool = Field(default=False)
    is_images_out_of_frame: bool = Field(default=False)
    images_unclear: bool = Field(default=False)
    is_odometer_reading_on: bool = Field(default=False)
    odometer_reading: int | None = Field(default=None)
    odometer_reading_text: str | None = Field(default=None)
    images_bad_lighting: bool = Field(default=False)
    rotation_angle: int = Field(default=0)


class BatchLicensePlateResponse(BaseModel):
    results: list[LicensePlateResult] = Field(
        description="List of extraction results for all images",
    )
