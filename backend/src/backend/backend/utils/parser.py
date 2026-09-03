import logging
from typing import Dict, List


logger = logging.getLogger(__name__)


def parse_optional_video_year(value) -> int | None:
    """Parse an optional whole, plausible calendar year."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("video_year must be an integer")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError("video_year must be a whole number")

    year = int(value)
    if not 1888 <= year <= 2100:
        raise ValueError("video_year must be between 1888 and 2100")
    return year


class Parser:
    def __init__(self):
        self.valid_parameter = {}

    def __call__(self, parameters: Dict = None, **kwargs) -> Dict:
        if not parameters:
            parameters = []

        task_parameter = {}
        for k, v in self.valid_parameter.items():
            if v.get("default"):
                task_parameter[k] = v.get("default")

        for p in parameters:
            if p["name"] not in self.valid_parameter:
                logger.error(f"[Parser] {p['name']} unknown")
                return None

            try:
                parser = self.valid_parameter[p["name"]].get("parser", lambda x: x)
                # TODO make this more generic
                if "path" in p:
                    value = parser(p["path"])
                else:
                    value = parser(p["value"])
                task_parameter[p["name"]] = value

            except Exception as e:
                logger.error(f"[Parser] {p['name']} could not parse ({e})")
                return None
        logger.debug(f"Task Parameter {task_parameter}")
        for k, v in self.valid_parameter.items():
            if v.get("required", None):
                if k not in task_parameter:
                    logger.error(f"[Parser] {k} is required")
                    return None

        return task_parameter
