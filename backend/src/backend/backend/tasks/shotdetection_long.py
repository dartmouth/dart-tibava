import logging
import uuid

from typing import Dict

from backend.models import PluginRun, PluginRunResult, Video, Timeline, TimelineSegment
from backend.plugin_manager import PluginManager

from ..utils.analyser_client import TaskAnalyserClient
from tibava_data import DataManager
from backend.utils.parser import Parser

from django.db import transaction

from .shotdetection import ShotDetection


@PluginManager.export_parser("shotdetection_long")
class ShotDetectionLongParser(Parser):
    def __init__(self):
        self.valid_parameter = {
            "timeline": {"parser": str, "default": "Shots"},
            "fps": {"parser": float, "default": 2.0},
        }


@PluginManager.export_plugin("shotdetection_long")
class ShotDetectionLong(ShotDetection):
    """Shot boundary detection for long videos.

    Same result as `shotdetection`, but runs on the `transnet_shotdetection_long`
    analyser, which streams the video through the model so memory use does not
    grow with the length of the video.
    """

    def __call__(
        self,
        parameters: Dict,
        video: Video = None,
        plugin_run: PluginRun = None,
        dry_run: bool = False,
        **kwargs,
    ):
        manager = DataManager(self.config["output_path"])
        client = TaskAnalyserClient(
            host=self.config["analyser_host"],
            port=self.config["analyser_port"],
            plugin_run_db=plugin_run,
            manager=manager,
        )

        video_id = self.upload_video(client, video)
        result = self.run_analyser(
            client,
            "transnet_shotdetection_long",
            parameters={"fps": parameters.get("fps")},
            inputs={"video": video_id},
            downloads=["shots"],
        )

        if result is None:
            raise Exception

        if dry_run or plugin_run is None:
            logging.warning("dry_run or plugin_run is None")
            return {}

        with transaction.atomic():
            with result[1]["shots"] as d:
                timeline = Timeline.objects.create(
                    video=video,
                    name=parameters.get("timeline"),
                    type=Timeline.TYPE_ANNOTATION,
                )
                for shot in d.shots:
                    segment_id = uuid.uuid4().hex
                    TimelineSegment.objects.create(
                        timeline=timeline,
                        id=segment_id,
                        start=shot.start,
                        end=shot.end,
                    )

                plugin_run_result_db = PluginRunResult.objects.create(
                    plugin_run=plugin_run,
                    data_id=d.id,
                    name="shots",
                    type=PluginRunResult.TYPE_SHOTS,
                )

                return {
                    "plugin_run": plugin_run.id.hex,
                    "plugin_run_results": [plugin_run_result_db.id.hex],
                    "timelines": {"shots": timeline.id.hex},
                    "data": {"shots": result[1]["shots"].id},
                }
