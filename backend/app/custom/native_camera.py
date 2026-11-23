"""Opt-in access to the built-in camera alongside the external feed."""

from os import getenv


def use_native_camera(requested: bool) -> bool:
    return requested and getenv("BAMBUDDY_CUSTOM_NATIVE_CAMERA", "1") == "1"
