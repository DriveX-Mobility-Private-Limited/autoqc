import requests
from django.conf import settings

from logger import get_logger

logging = get_logger()


class GalaxyClient:
    def __init__(self):
        self.base_url = settings.GALAXY_INTERNAL_API_URL.rstrip("/")
        self.api_key = settings.GALAXY_INTERNAL_API_KEY
        self.timeout = 30

    def _headers(self) -> dict:
        return {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json",
        }

    def get_vehicle(self, vehicle_id: int) -> dict | None:
        url = f"{self.base_url}/internal/api/autoqc/vehicle/{vehicle_id}/"
        try:
            response = requests.get(
                url, headers=self._headers(), timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json().get("data")
        except Exception:
            logging.exception(
                f"Failed to fetch vehicle {vehicle_id} from galaxy",
            )
            return None

    def get_inventory(self, c2c_inventory_id: int) -> dict | None:
        url = (
            f"{self.base_url}/internal/api/autoqc/"
            f"inventory/{c2c_inventory_id}/"
        )
        try:
            response = requests.get(
                url, headers=self._headers(), timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json().get("data")
        except Exception:
            logging.exception(
                f"Failed to fetch inventory {c2c_inventory_id} from galaxy",
            )
            return None

    def get_inventory_list(
        self,
        qc_status: str | None = None,
        page: int = 1,
    ) -> dict | None:
        url = f"{self.base_url}/internal/api/autoqc/inventories/"
        params = {"page": page}
        if qc_status:
            params["qc_status"] = qc_status
        try:
            response = requests.get(
                url,
                headers=self._headers(),
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json().get("data")
        except Exception:
            logging.exception("Failed to fetch inventory list from galaxy")
            return None

    def post_qc_result(self, callback_url: str, payload: dict) -> bool:
        try:
            response = requests.post(
                callback_url,
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return True
        except Exception:
            logging.exception(
                f"Failed to post QC result to {callback_url}",
            )
            return False
