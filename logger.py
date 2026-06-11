import sys
from functools import lru_cache

from loguru import logger

LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD at HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level> {extra} {exception}"
)

logger.remove()
logger.add(
    sys.stderr,
    format=LOG_FORMAT,
    level="INFO",
    backtrace=True,
    diagnose=True,
    enqueue=True,
    catch=True,
)


@lru_cache
def get_logger():
    return logger
