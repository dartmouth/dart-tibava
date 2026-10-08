from inference_ray.plugin import AnalyserPluginManager
from inference_ray.plugins.transnet_shotdetection import (
    TransnetShotdetection,
    default_parameters,
    provides,
    requires,
)

from tibava_utils import VideoDecoder
from tibava_data import Shot
from tibava_data import DataManager, Data

from typing import Callable, Dict

import numpy as np

default_config = {
    "data_dir": "/data/",
    "host": "localhost",
    "port": 6379,
    "model_name": "transnet",
    "model_device": "cpu",
    "model_file": "/models/transnet_shotdetection/transnet.pt",
}

# Window geometry of the TransNet model, mirrored from
# TransnetShotdetection.predict_frames: 100-frame windows, stride 50, of which
# the 50 center frames are kept (25 frames of context on either side).
WINDOW = 100
STRIDE = 50
CONTEXT = 25


@AnalyserPluginManager.export("transnet_shotdetection_long")
class TransnetShotdetectionLong(
    TransnetShotdetection,
    config=default_config,
    parameters=default_parameters,
    version="0.1",
    requires=requires,
    provides=provides,
):
    """Same model and output as `transnet_shotdetection`, but the video is
    decoded and fed to the model window by window, so memory use stays flat
    regardless of video length instead of holding (several copies of) every
    frame.

    Only `call` differs from the parent. Keep the windowing and padding in
    `_predict_stream` in sync with `TransnetShotdetection.predict_frames`.
    """

    def _predict_window(self, window: np.ndarray) -> np.ndarray:
        import torch

        with torch.no_grad(), torch.autocast(
            device_type=self.device, enabled=(self.device == "cuda")
        ):
            raw_result = self.model(torch.from_numpy(window[np.newaxis]).to(self.device))
        return raw_result[0].cpu().detach().numpy()[0, CONTEXT : CONTEXT + STRIDE, 0]

    def _predict_stream(self, frames, total_frames_estimate, callbacks):
        """Equivalent to predict_frames(np.stack(frames)) without materializing
        the whole video. `frames` is any iterator over (27, 48, 3) frames."""
        buffer = []
        predictions = []
        n_frames = 0
        last_frame = None

        def drain():
            # Run the model on every full window currently in the buffer.
            while len(buffer) >= WINDOW:
                predictions.append(self._predict_window(np.stack(buffer[:WINDOW])))
                del buffer[:STRIDE]
                progress = min(len(predictions) * STRIDE / total_frames_estimate, 0.99)
                self.update_callbacks(callbacks, progress=progress)

        for frame in frames:
            if n_frames == 0:
                # start padding: copies of the first frame
                buffer.extend([frame] * CONTEXT)
            buffer.append(frame)
            last_frame = frame
            n_frames += 1
            drain()

        if n_frames == 0:
            return np.zeros(0, dtype=np.float32)

        # end padding: copies of the last frame, 25 - 74 of them so that the
        # padded length is a whole number of strides
        no_padded_frames_end = CONTEXT + STRIDE - (n_frames % STRIDE or STRIDE)
        buffer.extend([last_frame] * no_padded_frames_end)
        drain()

        return np.concatenate(predictions)[:n_frames]

    def call(
        self,
        inputs: Dict[str, Data],
        data_manager: DataManager,
        parameters: Dict = None,
        callbacks: Callable = None,
    ) -> Dict[str, Data]:
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"

        if self.model is None:
            self.model = torch.jit.load(
                self.model_path, map_location=torch.device(device)
            )
            self.device = device

        self.update_callbacks(callbacks, progress=0.0)
        with (
            inputs["video"] as input_data,
            data_manager.create_data("ShotsData") as output_data,
        ):
            with input_data.open_video() as f_video:
                # VideoDecoder takes [width, height]. TransNetV2 expects 48 wide x
                # 27 high frames, i.e. (27, 48, 3) arrays, so no reshape is needed.
                # The parent plugin passes [27, 48] and then reshapes the
                # resulting (48, 27, 3) frames to (27, 48, 3), which scrambles
                # each frame. This plugin deliberately uses the canonical
                # preprocessing, so its shots can differ slightly from the parent's.
                video_decoder = VideoDecoder(
                    path=f_video,
                    max_dimension=[48, 27],
                    extension=f".{input_data.ext}",
                )
                total_frames_estimate = max(
                    video_decoder.duration() * video_decoder.fps(), 1
                )

                prediction = self._predict_stream(
                    (x.get("frame") for x in video_decoder),
                    total_frames_estimate,
                    callbacks,
                )

                shot_list = self.predictions_to_scenes(
                    prediction, parameters.get("threshold")
                )

                output_data.shots = [
                    Shot(
                        start=x[0].item() / video_decoder.fps(),
                        end=x[1].item() / video_decoder.fps(),
                    )
                    for x in shot_list
                ]

                self.update_callbacks(callbacks, progress=1.0)

                return {"shots": output_data}
