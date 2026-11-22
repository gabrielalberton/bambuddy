"""Optional lighter MJPEG profile for the known go2rtc feed in the homelab."""

import os

ENV_LIGHT_RTSP = "BAMBUDDY_CUSTOM_LIGHT_RTSP"
MAX_FPS = 8
MAX_WIDTH = 1280


def live_rtsp_input_options() -> list[str]:
    if os.environ.get(ENV_LIGHT_RTSP) != "1":
        return []
    # The go2rtc feed includes H.264 stream metadata in its SDP. Limit
    # analysis time on that known feed so FFmpeg can decode the next keyframe.
    return ["-analyzeduration", "750000", "-probesize", "262144"]


def live_rtsp_output_options(fps: int) -> list[str]:
    if os.environ.get(ENV_LIGHT_RTSP) != "1":
        return ["-r", str(fps)]
    # Drop frames before scaling and JPEG encoding. Keep the source aspect
    # ratio and avoid upscaling lower-resolution feeds.
    return ["-vf", f"fps={min(fps, MAX_FPS)},scale=w='min({MAX_WIDTH},iw)':h=-2"]
