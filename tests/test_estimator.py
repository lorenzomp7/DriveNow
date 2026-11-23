from drivenow.estimator import LaneQueue, QueueEstimator
from drivenow.hamburg.detectors import Loop, LoopEmulator


def passages(q, start, n, gap, on=0.8):
    """``n`` cars driving over the loop, one every ``gap`` seconds."""
    t = start
    for _ in range(n):
        q.event(t, True)
        q.event(t + on, False)
        t += gap
    return t


def test_queue_grows_while_a_car_stands_on_the_loop_and_drains_after():
    q = LaneQueue(max_cars=40)
    t = passages(q, 0.0, 30, 10.0)          # 30 cars in 300 s: 0.1 cars/s
    assert q.cars(t) == 0
    q.event(t, True)                         # the first car stops on the loop (red)
    assert q.cars(t + 2.0) == 0              # not yet: could be a car passing
    assert q.cars(t + 40.0) == 5             # 1 + 0.1 x 40
    q.event(t + 40.0, False)                 # green: the queue drives off
    assert q.cars(t + 40.5) == 5
    passages(q, t + 41.0, 3, 2.0)
    assert q.cars(t + 46.5) == 2
    assert q.cars(t + 60.0) == 0             # no car for a while: the queue has gone


def test_a_queue_never_exceeds_the_road():
    q = LaneQueue(max_cars=6)
    passages(q, 0.0, 60, 5.0)
    q.event(300.0, True)
    assert q.cars(900.0) == 6


def test_a_car_driving_through_ends_the_queue():
    q = LaneQueue(max_cars=40)
    t = passages(q, 0.0, 30, 10.0)
    q.event(t, True)
    q.event(t + 40.0, False)
    q.drove_through()
    assert q.cars(t + 41.0) == 0


def test_merge_adds_the_cars_the_phones_do_not_show_and_reaches_back():
    lengths = {"near": 8.0, "far": 100.0}
    est = QueueEstimator([("near", 0)], lengths, upstream=lambda e: "far" if e == "near" else None)
    q = est.lanes[("near", 0)]
    t = passages(q, 0.0, 60, 5.0)            # 0.2 cars/s
    q.event(t, True)
    occ = est.merge({}, t + 20.0)            # 1 + 0.2 x 20 = 5 cars standing
    assert sum(1 for v in occ.values() for _, s in v if s == 0.0) == 5
    assert len(occ["near"]) == 1 and len(occ["far"]) == 4
    # A DriveNow car already shows two of them on "far": only the others are added.
    occ = est.merge({"far": [(95.0, 0.0), (88.0, 0.0)]}, t + 20.0)
    assert len(occ["far"]) == 4
    assert est.standing(t + 20.0) == {"near": 5}


def test_loop_emulator_counts_cars_as_the_real_detectors_do():
    lp = Loop("1_1", 7, "a", 0, 98.0)
    em = LoopEmulator([lp])
    assert em.step([("a", 0, 90.0)]) == []
    assert em.step([("a", 0, 99.0)]) == [(lp, True)]       # front past the loop
    assert em.step([("a", 1, 99.0)]) == [(lp, False)]      # other lane
    em.step([("a", 0, 98.5)])
    em.step([("a", 0, 102.5)])                              # rear still over it
    assert lp.occupied and lp.passages == 2
    em.step([("b", 0, 5.0)])
    assert not lp.occupied


def test_with_the_light_the_queue_grows_on_red_from_the_first_car_at_the_line():
    q = LaneQueue(max_cars=40)
    q.signal(0.0, True)
    t = passages(q, 0.0, 30, 10.0)          # 0.1 cars/s, all through on green
    assert q.cars(t) == 0
    q.signal(t, False)                       # red
    assert q.cars(t + 20.0) == 0             # nobody at the line yet: no queue
    q.event(t + 25.0, True)                  # the first car reaches the line and stands
    assert q.cars(t + 25.0) == 1
    assert q.cars(t + 45.0) == 3             # 1 + 0.1 x 20, however often it is asked
    q.signal(t + 45.0, True)                 # green: cars leave one per passage
    q.event(t + 46.0, False)                 # the first one, that stood through red
    assert q.cars(t + 46.5) == 2             # 3 + 0.1 x 1.5 - 1
    passages(q, t + 47.0, 2, 2.0)
    passages(q, t + 51.0, 2, 2.0)
    assert q.cars(t + 54.0) == 0             # all gone: stays gone for the rest of green
    assert q.cars(t + 70.0) == 0


def test_a_queue_left_over_at_the_end_of_green_carries_into_red():
    q = LaneQueue(max_cars=40)
    q.signal(0.0, True)
    t = passages(q, 0.0, 60, 5.0)            # 0.2 cars/s
    q.signal(t, False)
    q.event(t + 1.0, True)                   # a car stops at the line
    q.signal(t + 51.0, True)                 # 1 + 0.2 x 50 = 11 waiting
    q.event(t + 52.0, False)
    passages(q, t + 53.0, 3, 2.0)            # only 4 get through
    q.event(t + 59.0, True)                  # the next car stops on the loop
    q.signal(t + 59.0, False)                # red again with 11 + 0.2 x 8 - 4 ~ 9 left
    assert 7 <= q.cars(t + 59.0) <= 9         # (the car on the loop counts as a passage)
    assert q.cars(t + 69.0) > q.cars(t + 59.0)  # and growing


def test_no_queue_on_red_while_the_loop_is_free():
    q = LaneQueue(max_cars=40)
    q.signal(0.0, True)
    t = passages(q, 0.0, 30, 10.0)
    q.signal(t, False)
    assert q.cars(t + 120.0) == 0


def test_estimator_passes_the_light_to_its_lanes():
    est = QueueEstimator([("a", 0)], {"a": 100.0}, upstream=lambda e: None)
    q = est.lanes[("a", 0)]
    est.signal("a", 0, 0.0, True)
    t = passages(q, 0.0, 30, 10.0)
    est.signal("a", 0, t, False)
    est.event("a", 0, t + 5.0, True)
    assert est.standing(t + 25.0) == {"a": 3}
