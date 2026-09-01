import os
import tempfile
from unittest.mock import patch

from django.test import TestCase
from django.db import transaction

from backend.models import PluginRun, PluginRunResult, TibavaUser, Timeline, Video
from backend.plugin_manager import PluginManager
from backend.tasks.clip_ontology import CLIPOntology
from backend.tasks.place_identification import InsightfaceIdentification


class ContextData:
    def __init__(self, data_id):
        self.id = data_id

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class ConceptData(ContextData):
    def create_data(self, *_args):
        return ContextData("concept")


class FakeDataManager:
    def create_data(self, *_args):
        return ConceptData("concepts")


class AggregatedScalars(ContextData):
    def __init__(self):
        super().__init__("aggregate-id")
        self.index = ["beach", "city"]
        self.data = [ContextData("beach-id"), ContextData("city-id")]

    def extract_all(self, _manager):
        pass


class FailingTimelineTask:
    def __call__(self, _parameters, *, video, **_kwargs):
        with transaction.atomic():
            Timeline.objects.create(video=video, name="partial timeline")
            raise RuntimeError("simulated analyser failure")


class TimelineGenerationTaskTests(TestCase):
    def setUp(self):
        self.user = TibavaUser.objects.create_user(
            username="timeline-test-user",
            email="timeline-test-user@example.invalid",
            password="not-used",
        )
        self.video = Video.objects.create(
            owner=self.user,
            name="timeline-test-video",
            ext="mp4",
            duration=1.0,
        )

    def create_run(self, plugin):
        return PluginRun.objects.create(video=self.video, type=plugin)

    @patch("backend.tasks.place_identification.TaskAnalyserClient")
    @patch("backend.tasks.place_identification.DataManager", return_value=FakeDataManager())
    def test_place_identification_creates_timeline(self, _manager, _client):
        task = InsightfaceIdentification()
        task.upload_video = lambda *_args: "video-id"
        responses = iter(
            [
                ({"embeddings": "embeddings-id"}, {}),
                ({"probs": "probs-id"}, {}),
                ({}, {"aggregated_scalar": ContextData("place-data-id")}),
            ]
        )
        task.run_analyser = lambda *_args, **_kwargs: next(responses)

        plugin_run = self.create_run("place_identification")
        result = task(
            {"timeline": "Places", "fps": 2, "index": -1, "cluster_id": -1},
            video=self.video,
            user=self.user,
            plugin_run=plugin_run,
        )

        timeline = Timeline.objects.get(video=self.video)
        self.assertEqual(timeline.name, "Places")
        self.assertEqual(result["timelines"]["annotations"], timeline.id.hex)
        self.assertEqual(result["data"]["annotations"], "place-data-id")
        self.assertEqual(PluginRunResult.objects.count(), 1)

    @patch("backend.tasks.clip_ontology.TaskAnalyserClient")
    @patch("backend.tasks.clip_ontology.DataManager", return_value=FakeDataManager())
    def test_clip_ontology_without_shots_creates_top_level_timelines(
        self, _manager, client
    ):
        client.return_value.upload_data.return_value = "concepts-id"
        task = CLIPOntology()
        task.upload_video = lambda *_args: "video-id"
        aggregate_data = AggregatedScalars()
        responses = iter(
            [
                ({"embeddings": "embeddings-id"}, {}),
                ({"probs": "probs-id"}, {}),
                ({}, {"aggregated_scalars": aggregate_data}),
            ]
        )
        task.run_analyser = lambda *_args, **_kwargs: next(responses)

        with tempfile.NamedTemporaryFile("w", delete=False) as concepts_file:
            concepts_file.write("beach,a beach\ncity,a city\n")
            concepts_path = concepts_file.name
        self.addCleanup(lambda: os.remove(concepts_path))

        plugin_run = self.create_run("clip_ontology")
        result = task(
            {"timeline": "Concepts", "concept_csv": concepts_path, "fps": 2.0},
            video=self.video,
            user=self.user,
            plugin_run=plugin_run,
        )

        timelines = Timeline.objects.filter(video=self.video).order_by("name")
        self.assertEqual([timeline.name for timeline in timelines], ["beach", "city"])
        self.assertTrue(all(timeline.parent is None for timeline in timelines))
        self.assertNotIn("annotations", result["timelines"])
        self.assertEqual(len(result["plugin_run_results"]), 2)
        self.assertEqual(PluginRunResult.objects.count(), 2)

    def test_plugin_failure_marks_run_error_and_rolls_back_timelines(self):
        with patch.dict(
            PluginManager._plugins,
            {"failing_timeline": lambda: FailingTimelineTask()},
        ):
            result = PluginManager()(
                "failing_timeline",
                video=self.video,
                user=self.user,
                run_async=False,
            )

        plugin_run = PluginRun.objects.get(video=self.video)
        self.assertFalse(result["status"])
        self.assertEqual(plugin_run.status, PluginRun.STATUS_ERROR)
        self.assertFalse(Timeline.objects.filter(video=self.video).exists())
