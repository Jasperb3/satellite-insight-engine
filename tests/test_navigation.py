from satviz.navigation import MIN_BUFFER, MOVEMENT_SCALE, ZOOM_STEP, handle_movement


def test_north_increases_latitude():
    assert handle_movement(10.0, 20.0, 2500, "w") == (10.0 + MOVEMENT_SCALE, 20.0, 2500)


def test_south_decreases_latitude():
    assert handle_movement(10.0, 20.0, 2500, "s") == (10.0 - MOVEMENT_SCALE, 20.0, 2500)


def test_west_decreases_longitude():
    assert handle_movement(10.0, 20.0, 2500, "a") == (10.0, 20.0 - MOVEMENT_SCALE, 2500)


def test_east_increases_longitude():
    assert handle_movement(10.0, 20.0, 2500, "d") == (10.0, 20.0 + MOVEMENT_SCALE, 2500)


def test_zoom_in_reduces_buffer():
    assert handle_movement(10.0, 20.0, 2500, "z") == (10.0, 20.0, 2500 - ZOOM_STEP)


def test_zoom_in_clamps_at_minimum():
    _, _, buffer = handle_movement(10.0, 20.0, MIN_BUFFER, "z")
    assert buffer == MIN_BUFFER


def test_zoom_out_increases_buffer():
    assert handle_movement(10.0, 20.0, 2500, "x") == (10.0, 20.0, 2500 + ZOOM_STEP)


def test_unknown_command_is_noop():
    assert handle_movement(10.0, 20.0, 2500, "k") == (10.0, 20.0, 2500)


def test_command_is_case_insensitive_and_trimmed():
    assert handle_movement(10.0, 20.0, 2500, " W ") == (10.0 + MOVEMENT_SCALE, 20.0, 2500)
