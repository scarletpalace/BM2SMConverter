import operator
from fractions import Fraction
from bisect import bisect_left, bisect_right
from typing import Callable, List, Tuple

from bm2sm.custom_fake_types import BPM, Beat, BeatStop, ChartPosition, Measure, MsStop, Time, TimeSignature
from modules.decorators import transform_args, transform_return
from modules.fake_types import NonNegativeInt, PositiveFraction


class TimingSectionManager(object):
    """Manager for all manners of timing changes"""
    _time_signature_changes = ...  # type: List[Tuple[NonNegativeInt, TimeSignature]]
    _ms_stops = ...  # type: List[Tuple[ChartPosition, MsStop]]
    _position_to_time = ...  # type: Callable[ChartPosition, Time]
    _fixed = ...  # type: bool
    _bpm_changes = ...  # type: List[Tuple[ChartPosition, BPM]]

    def __init__(self):
        self._bpm_changes = []
        # The BPM changes in position order, for looking up the BPM at a position. Rebuilt after every new change
        self._sorted_bpm_changes = None
        self._fixed = False
        self._position_to_time = None
        self._ms_stops = []
        self._time_signature_changes = []

    @transform_args(..., Measure, BeatStop)
    def add_beat_stop(self, measure, stop_duration):
        # Stepmania does not have real beat stops so we'll have to approximate by adding a close enough ms stop.
        #   BPM changes cannot be added as they will change the topology of the chart.
        stop_duration = Fraction(stop_duration, 192)
        if self._sorted_bpm_changes is None:
            # A stable sort, so of several changes at one position the last one added still wins
            self._sorted_bpm_changes = sorted(self._bpm_changes, key=operator.itemgetter(0))
            self._sorted_bpm_starts = [position for position, _ in self._sorted_bpm_changes]
        closest_bpm = self._sorted_bpm_changes[bisect_right(self._sorted_bpm_starts, measure) - 1][1]
        # Kept exact rather than rounded to milliseconds: gimmick charts can have hundreds of stops far shorter
        #   than that at extreme BPMs, and rounding each of them would add up to the audio drifting off the notes
        self._ms_stops.append((measure, stop_duration * Fraction(240, closest_bpm)))

    @transform_args(..., Measure, MsStop)
    def add_ms_stop(self, measure, stop_duration):
        self._ms_stops.append((measure, Fraction(stop_duration, 1000)))

    @transform_args(..., Measure, BPM)
    def add_bpm_change(self, measure, new_bpm):
        self._bpm_changes.append((measure, new_bpm))
        self._sorted_bpm_changes = None

    @transform_args(..., Measure, TimeSignature)
    def add_time_signature_change(self, measure, value):
        temp = dict(self._time_signature_changes)
        temp[NonNegativeInt(measure)] = PositiveFraction(value)
        self._time_signature_changes = list(temp.items())
        self._time_signature_changes.sort(key=operator.itemgetter(0))

    # This must be called after topology of the notefield has been defined.
    # This will make this object functionally immutable.

    def fix(self):
        all_lists = [self._bpm_changes, self._ms_stops]

        for lst in all_lists:
            beats_present = set()
            result = []
            for beat, value in reversed(lst):
                if beat not in beats_present:
                    beats_present.add(beat)
                    result.append((beat, value))
            result = sorted(result, key=operator.itemgetter(0))
            lst.clear()
            lst += result

        # A BPM change to the BPM that is already in effect changes nothing
        self._bpm_changes = [T
                             for i, T in enumerate(self._bpm_changes)
                             if i == 0 or T[1] != self._bpm_changes[i - 1][1]]

        # The time at the start of every BPM section and the total length of the stops up to every stop are
        #   computed once, so finding the time of a position is a binary search instead of going through
        #   every BPM change and stop, which gimmick charts have thousands of
        bpm_starts = [position for position, _ in self._bpm_changes]
        bpm_coefficients = [Fraction(240, bpm) for _, bpm in self._bpm_changes]
        bpm_start_times = [Fraction(0)]
        for i in range(1, len(bpm_starts)):
            bpm_start_times.append(bpm_start_times[-1] + (bpm_starts[i] - bpm_starts[i - 1]) * bpm_coefficients[i - 1])

        stop_starts = [position for position, _ in self._ms_stops]
        stops_total = [Fraction(0)]
        for _, duration in self._ms_stops:
            stops_total.append(stops_total[-1] + duration)

        @transform_args(Measure)
        @transform_return(Time)
        def calculate_time_by_position(position):
            section = max(0, bisect_right(bpm_starts, position) - 1)
            bpm_time = bpm_start_times[section] + max(0, position - bpm_starts[section]) * bpm_coefficients[section]
            # A stop delays everything after it, but not what is at its own position
            return bpm_time + stops_total[bisect_left(stop_starts, position)]

        self._position_to_time = calculate_time_by_position
        self._fixed = True


    def _split_fraction_for_string(self, fraction):
        integer_part = fraction.numerator // fraction.denominator
        fractional_part = fraction.numerator % fraction.denominator
        assert 1000 % fraction.denominator == 0
        fractional_part *= 1000 // fraction.denominator

        return integer_part, fractional_part


    @property
    def position_to_time(self):
        return self._position_to_time

    def sm_position_to_time(self):
        """A function giving the time of a position (in measures, on the SM grid) as SM games see it from the SM file.

        They put BPM changes and stops on rows of 1/48 beat and keep only the last of several on one row,
        so for charts with very finely placed timing changes this can differ from the chart's real timing."""
        bpms = {}
        for measure, bpm in self._bpm_changes:
            bpms[round(Beat(4 * measure) * 48)] = bpm
        stops = {}
        for measure, duration in self._ms_stops:
            if round(duration, 6) > 0:
                stops[round(Beat(4 * measure) * 48)] = round(duration, 6)

        bpm_rows = sorted(bpms)
        seconds_per_row = [Fraction(60, 48 * bpms[T]) for T in bpm_rows]
        bpm_start_times = [Fraction(0)]
        for i in range(1, len(bpm_rows)):
            bpm_start_times.append(bpm_start_times[-1] + (bpm_rows[i] - bpm_rows[i - 1]) * seconds_per_row[i - 1])
        stop_rows = sorted(stops)
        stops_total = [Fraction(0)]
        for row in stop_rows:
            stops_total.append(stops_total[-1] + stops[row])

        def calculate_time(position):
            row = position * 192
            section = max(0, bisect_right(bpm_rows, row) - 1)
            bpm_time = bpm_start_times[section] + max(0, row - bpm_rows[section]) * seconds_per_row[section]
            return bpm_time + stops_total[bisect_left(stop_rows, row)]

        return calculate_time

    def main_bpm(self, end_position):
        """The BPM the chart spends the most time at, up to `end_position`."""
        durations = {}
        for i, (position, bpm) in enumerate(self._bpm_changes):
            next_position = self._bpm_changes[i + 1][0] if i + 1 < len(self._bpm_changes) else end_position
            durations[bpm] = durations.get(bpm, 0) + max(0, next_position - position) * Fraction(240, bpm)
        return max(durations, key=durations.get)

    def single_bpm_string(self, bpm):
        return '0.000={}.{:03g}'.format(*self._split_fraction_for_string(bpm))

    @property
    def bpm_string(self):
        return ",".join(
            '{}.{:03g}={}.{:03g}'.format(
                *self._split_fraction_for_string(Beat(4 * measure)),
                *self._split_fraction_for_string(value))
            for measure, value in self._bpm_changes
        )

    @property
    def bpm_dict(self):
        return dict(self._bpm_changes)

    @property
    def bpm_list(self):
        return list(self._bpm_changes)

    @property
    def is_fixed(self):
        return self._fixed

    @property
    def is_not_fixed(self):
        return not self.is_fixed

    @property
    def ms_stops_string(self):
        # Stop lengths are written with more precision than milliseconds, and the ones too short even for that are left
        #   out, since SM cannot do anything with them
        return ",".join(
            '{}.{:03g}={:.6f}'.format(
                *self._split_fraction_for_string(Beat(4 * measure)),
                float(value))
            for measure, value in self._ms_stops
            if round(value, 6) > 0
        )

    @property
    def ms_stops_dict(self):
        return dict(self._ms_stops)

    @property
    def ms_stops_list(self):
        return list(self._ms_stops)

    @property
    def time_sgn_string(self):
        return ",".join(
            '{}.{:03g}={}={}'.format(*self._split_fraction_for_string(Beat(4 * measure)),
                                     sgn.numerator,
                                     sgn.denominator)
            for measure, sgn in self._time_signature_changes
        )

    @property
    def time_sgn_dict(self):
        return dict(self._time_signature_changes)

    @property
    def time_sgn_list(self):
        return list(self._time_signature_changes)
