from celery import shared_task

from qc.services.image_service import ImageService
from logger import get_logger

logging = get_logger()


@shared_task
def rotate_image_and_clear_cache(
    image_url: str,
    rotation_angle: int,
) -> bool:
    rotation_service = ImageService()
    success = rotation_service.rotate_and_upload(
        image_url=image_url,
        rotation_angle=rotation_angle,
    )
    if success:
        rotation_service.purge_image_cache(image_url)
        logging.info(f"ImageKit purge completed: {image_url}")
    return success


@shared_task
def purge_image_cache(image_url: str) -> None:
    rotation_service = ImageService()
    rotation_service.purge_image_cache(image_url)
    logging.info(f"ImageKit purge completed: {image_url}")
