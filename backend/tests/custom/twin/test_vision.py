from backend.app.custom.twin.vision import public_pose


def test_only_recent_finite_course_coordinates_enter_sse():
    assert public_pose({"at": 10.0, "x": 268, "y": 80, "z": 43.1, "image": "..."}, 10.4) == {
        "at": 10.0, "x": 268, "y": 80, "z": 43.1,
    }
    assert public_pose({"at": 10.0, "x": 273, "y": float("nan"), "z": 20}, 10.1) == {"at": 10.0, "z": 20}
    assert public_pose({"at": 10.0, "x": 20}, 11.0) is None
    assert public_pose({"at": 10.0, "x": 20}, 9.8) is None
    assert public_pose({"at": True, "x": 20}, 1.1) is None
    assert public_pose({"at": 10.0, "x": True, "y": "100"}, 10.1) is None
