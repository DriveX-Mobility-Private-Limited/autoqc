import json
import time
from datetime import timedelta

import zstandard as zstd
from django_redis import get_redis_connection

from logger import get_logger

logging = get_logger()


class VehicleAnalysisRedisService:
    """
    vehicle_analysis:{transaction_id}   (HASH)
    ├─ front  → compressed bytes
    ├─ rear   → compressed bytes
    ├─ left   → compressed bytes
    └─ right  → compressed bytes
    """

    REDIS_KEY_PREFIX = "vehicle_analysis"
    EXPIRY_SECONDS = int(timedelta(days=30).total_seconds())

    def __init__(self):
        self.redis = get_redis_connection("default")
        self._compressor = zstd.ZstdCompressor(level=6)
        self._decompressor = zstd.ZstdDecompressor()

    def save_result(
        self,
        transaction_id: str,
        angle: str,
        result: dict,
    ) -> None:
        try:
            result = result.copy()
            result["timestamp"] = int(time.time())
            raw = json.dumps(result, separators=(",", ":")).encode()
            compressed = self._compressor.compress(raw)

            redis_key = self._get_key(transaction_id)
            pipe = self.redis.pipeline(transaction=True)
            pipe.hset(redis_key, angle, compressed)
            pipe.expire(redis_key, self.EXPIRY_SECONDS)
            pipe.execute()

            logging.info(
                "Saved vehicle analysis: tx=%s angle=%s size=%dB→%dB",
                transaction_id,
                angle,
                len(raw),
                len(compressed),
            )
        except Exception:
            logging.exception(
                "Failed saving vehicle analysis: tx=%s angle=%s",
                transaction_id,
                angle,
            )

    def get_all_results(self, transaction_id: str) -> dict[str, dict]:
        try:
            redis_key = self._get_key(transaction_id)
            data = self.redis.hgetall(redis_key)

            if not data:
                return {}

            results: dict[str, dict] = {}
            for angle_bytes, compressed in data.items():
                angle = angle_bytes.decode()
                decompressed = self._decompressor.decompress(compressed)
                results[angle] = json.loads(decompressed)

        except Exception:
            logging.exception(
                "Failed retrieving vehicle analysis: tx=%s",
                transaction_id,
            )
            return {}
        else:
            return results

    def _get_key(self, transaction_id: str) -> str:
        return f"{self.REDIS_KEY_PREFIX}:{transaction_id}"
