import asyncio
import logging
from ray import serve
from typing import Dict
from ray.serve import Application

from tibava_data import DataManager
from inference_ray.plugin import AnalyserPluginManager, AnalyserPlugin


@serve.deployment
class Deployment:
    def __init__(self, plugin: AnalyserPlugin, data_manager: DataManager) -> None:
        self.plugin = plugin
        self.data_manager = data_manager
        # Plugins lazily initialize shared, non-thread-safe state on first use
        # (e.g. `if self.model is None: self.model = <load model>`). This lock
        # ensures at most one request executes the plugin body at a time per
        # replica, preserving the serialization that used to happen implicitly
        # when the plugin call blocked the single-threaded event loop.
        self._plugin_lock = asyncio.Lock()

    async def __call__(self, request) -> Dict[str, str]:
        data = await request.json()
        inputs = data.get("inputs")
        parameters = data.get("parameters")
        logging.debug("inputs=%s parameters=%s", inputs, parameters)

        plugin_inputs = {}
        for name, id in inputs.items():
            data = self.data_manager.load(id)
            plugin_inputs[name] = data

        # The plugin call runs synchronous, CPU-bound inference (model
        # loading, video/audio decoding, torch/onnx forward passes) that can
        # take anywhere from seconds to several minutes. Running it directly
        # on this coroutine blocks the replica's single-threaded asyncio
        # event loop for the whole duration. Ray Serve's background health
        # watchdog probes that same loop periodically; if it can't get a
        # response for long enough (default: 3 consecutive missed probes)
        # it raises "User event loop unresponsive" and the replica is killed
        # mid-request, which is what shows up as repeated health-check
        # failures/restarts in the controller logs. Offload the blocking
        # call to a worker thread so the event loop stays responsive.
        #
        # The lock below serializes concurrent requests to this replica
        # (Ray Serve allows several in flight per replica by default) so the
        # worker thread never races another in-flight call over the plugin's
        # lazily-initialized model state.
        async with self._plugin_lock:
            results = await asyncio.to_thread(
                self.plugin,
                plugin_inputs,
                data_manager=self.data_manager,
                parameters=parameters,
            )

        return {x: y.id for x, y in results.items()}


def app_builder(args) -> Application:
    logging.warning(args)
    data_manager = DataManager(args.get("data_path"))
    manager = AnalyserPluginManager()
    plugin = manager.build_plugin(args.get("model"), args.get("params", {}))

    return Deployment.bind(plugin, data_manager)
