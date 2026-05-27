from enum import Enum


class C2CQCStatus(Enum):
    PENDING = "Pending"
    PASSED = "Passed"
    FAILED = "Failed"
    UNDER_REVIEW = "Under Review"
    QUERY_RAISED = "Query Raised"
    RE_REVIEW = "Re-Review"
    NEEDS_REVIEW = "Needs Review"

    @classmethod
    def values(cls) -> list[str]:
        return [status.value for status in cls]

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in cls._value2member_map_


class C2CQCSubStatusEnum(Enum):
    """C2C inventory sub_status (reason of status)"""

    # Delisting
    SOLD_VIA_DRIVEX = "Sold via DriveX"
    SOLD_TO_DRIVEX = "Sold to DriveX"
    CLOSED_UNDER_DAP = "Closed under DAP"
    GETTING_MULTIPLE_CALLS = "Getting Multiple Calls"
    LOW_MEETING_ACCEPTANCE_RATE = "Low Meeting Acceptance Rate"
    NOT_INTERESTED_IN_SELLING = "Not Interested in Selling"
    SOLD_THROUGH_COMPETITION = "Sold through competition"
    SOLD_TO_FAMILY_AND_FRIENDS = "Sold to family and friends"
    SOLD_THROUGH_OTHER_CHANNELS = "Sold through other channels"
    PRICING_EXPECTATION_NOT_MET = "Pricing expectation not met"
    C2C_SALE_IN_PROGRESS = "C2C sale in progress with buyer"

    # Query Raised
    KYC_PROCESS_PENDING = "KYC process pending"
    MODEL_MISMATCH = "Model Mismatch"
    IMAGE_OBJECT_VISIBLE = "Object visible (human, more vehicles)"
    IMAGE_OUT_OF_FRAME = "Images out of frame"
    IMAGE_ROTATION_ISSUE = "Rotation issue"
    IMAGE_UNCLEAR = "Images unclear"
    IMAGE_ODOMETER_NOT_VISIBLE = "Odometer reading not visible"
    IMAGE_REGISTRATION_NUMBER_MISMATCH = "Registration Number Mismatch"
    IMAGE_SCREENSHOT = "Screenshot images"
    IMAGE_BAD_LIGHTING = "Bad lighting"
    IMAGE_AI_GENERATED = "AI generated images"
    IMAGE_DUPLICATE_OR_MISSING_SIDES = "Duplicate/missing sides"
    AI_RESPONSE_NOT_AVAILABLE = "AI Response Not Available"
    REGISTRATION_NUMBER_NOT_FOUND = "Registration Number Not Found"

    # QC Rejected
    ELECTRIC_VEHICLE = "Electric Vehicle"

    # Buyer dropped
    DROPPED = "Dropped"

    @classmethod
    def values(cls) -> list[str]:
        return [op.value for op in cls]

    @classmethod
    def get_enum_by_name(cls, key: str) -> "C2CQCSubStatusEnum":
        return next((item for item in cls if item.name == key), None)


class C2CQCSource(Enum):
    AI = "AI"
    MANUAL = "Manual"


class PresignedUrlOperationType(Enum):
    GET = "get"
    PUT = "put"

    @classmethod
    def values(cls):
        return [item.value for item in cls]


class C2CInventoryStatus(Enum):
    PENDING = "Pending"
    AVAILABLE = "Available"
    NEEDS_UPDATE = "Needs Update"
