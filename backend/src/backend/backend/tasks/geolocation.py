from typing import Dict

from backend.models import PluginRun, Video, TibavaUser
from backend.plugin_manager import PluginManager
from backend.utils.parser import Parser
from backend.utils.task import Task


@PluginManager.export_parser("geolocation")
class GeolocationParser(Parser):
    def __init__(self):
        self.valid_parameter = {
            "timeline": {"parser": str, "default": "Geolocation"},
            "shot_timeline_id": {"default": None},
            "fps": {"parser": float, "default": 2},
            "confidence_threshold": {"parser": float, "default": 0.3},
            "year": {"parser": str, "default": None},
        }


@PluginManager.export_plugin("geolocation")
class Geolocation(Task):
    def __call__(
        self,
        parameters: Dict,
        video: Video = None,
        user: TibavaUser = None,
        plugin_run: PluginRun = None,
        dry_run: bool = False,
        **kwargs,
    ):
        raise NotImplementedError(
            "Geolocation has no model integration yet; this plugin is registered "
            "so it can be configured and run from the UI ahead of that work."
        )
