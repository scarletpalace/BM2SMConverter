from fractions import Fraction
from itertools import count as iter_count

from os import path
from subprocess import DEVNULL, PIPE, run

from pydub import AudioSegment
from pydub.audio_segment import fix_wav_headers

from bm2sm.definitions import DEFAULT_FRAME_RATE, Keys, warn
from modules.decorators import transform_args, transform_return
from modules.fake_types import CastableToInt, NonNegativeInt, PositiveInt
from .custom_fake_types import Character, ChartPosition, Measure, Message, Segment, Time


class Datum(object):
    """Basic class representing a channel message from BM files."""
    _initial_measure = ...  # type: Measure
    _id = ...  # type: int
    FREE_ID = 0  # type: int

    @transform_args(..., Segment, Measure, ChartPosition, PositiveInt)
    def __init__(self, value, measure, position, measure_split):
        assert position < measure_split

        self.value = value
        self._id = self.FREE_ID
        self._initial_measure = measure
        self._initial_position = self.initial_measure + Fraction(position, measure_split)

        self._global_position = self.initial_position

        Datum.FREE_ID += 1

    @classmethod
    @transform_args(..., Message, Measure)
    def from_message(cls, message, measure):
        pairs = [''.join(T) for T in zip(message[::2], message[1::2])]

        measure_split = len(pairs)
        enumerated_pairs = zip(iter_count(), pairs)

        result = [
            cls(datum, measure, position, measure_split)
            for position, datum in enumerated_pairs
            if datum != '00'
        ]

        return result

    @property
    def global_position(self):
        return self._global_position

    @global_position.setter
    def global_position(self, value: ChartPosition):
        value = ChartPosition(value)
        self._global_position = value

    @property
    def initial_measure(self):
        return self._initial_measure

    @property
    def initial_position(self):
        return self._initial_position


class NotefieldObject(object):
    """Basic object representing an object on a notefield."""
    position = ...  # type: ChartPosition
    measure = ...  # type: NonNegativeInt
    key = ...  # type: CastableToInt
    symbol = ...  # type: Character

    @transform_args(..., Measure, CastableToInt, Character)
    def __init__(self, position, key, symbol):
        assert key in Keys.__dict__.values()
        self.position = position
        self.measure = position.numerator // position.denominator
        self.key = key
        self.symbol = symbol


class Sound(object):
    """Basic object representing a sound in the audio file."""
    _id = ...  # type: Segment
    sound = ...  # type: AudioSegment
    _time = ...  # type: Time

    @transform_args(..., Segment, ..., Time)
    def __init__(self, wav_id, sound, time):
        # `id` ended up unused after rewriting audio file baking.
        #   It was used to group sounds in layers and simulate sounds being cutoff
        #     as described in the reference
        assert sound

        self._id = wav_id
        self.sound = sound

        if self.sound.frame_rate != DEFAULT_FRAME_RATE:
            self.sound = self.sound.set_frame_rate(DEFAULT_FRAME_RATE)

        self._time = Time(1000 * time)
        # Used a lot while mixing, and computing it with fractions every time is slow
        self._start_time_frames = NonNegativeInt(Fraction(DEFAULT_FRAME_RATE, 1000) * self._time)

    @property
    def wav_id(self):
        return self._id

    @property
    @transform_return(Time)
    def start_time_ms(self):
        return self._time

    @property
    def start_time_frames(self):
        return self._start_time_frames

    @property
    @transform_return(Time)
    def duration_ms(self):
        return 1000 * Fraction(self.duration_frames, self.sound.frame_rate)

    @property
    @transform_return(NonNegativeInt)
    def duration_frames(self):
        return int(self.sound.frame_count())

    @property
    @transform_return(Time)
    def end_time_ms(self):
        return self.duration_ms + self.start_time_ms

    @property
    @transform_return(NonNegativeInt)
    def end_time_frames(self):
        return self.start_time_frames + self.duration_frames


def _decode_sound(location):
    if path.splitext(location)[1].lower() not in ('.ogg', '.mp3'):
        return AudioSegment.from_file(location)
    # pydub runs ffprobe before decoding to choose the sample format, but lossy formats always end up as 16 bit.
    #   Skipping it halves the time, which matters with charts that have a thousand keysounds.
    process = run([AudioSegment.converter, '-v', 'error', '-i', location, '-vn', '-acodec', 'pcm_s16le', '-f', 'wav', '-'],
                  stdin=DEVNULL, stdout=PIPE, stderr=PIPE)
    if process.returncode != 0:
        raise RuntimeError(process.stderr.decode(errors='replace').strip())
    # Same as what pydub does with ffmpeg output, since the piped WAV header has no sizes
    data = bytearray(process.stdout)
    fix_wav_headers(data)
    return AudioSegment(data=bytes(data))


class SoundSample(object):
    """Basic object representing a loaded keynote sound."""

    _location = ...  # type: str
    _segment = ...  # type: AudioSegment

    def __init__(self, location):
        self._location = location
        self._segment = None

    @property
    def segment(self):
        if self._segment is not None:
            return self._segment or None
        try:
            segment = _decode_sound(self._location)
        except Exception as e:
            # Players skip sounds they cannot decode, so the chart is still converted
            warn('Cannot read sound file, skipping it: {} ({})'.format(self._location, e))
            self._segment = False
            return None
        # Some files are cut off in the middle of a frame, which the mixer cannot handle, so the partial frame is dropped
        partial_frame = len(segment.raw_data) % segment.frame_width
        if partial_frame:
            segment = segment._spawn(segment.raw_data[:-partial_frame])
        # Resampled once here, instead of every time the sound is placed in the chart
        if segment.frame_rate != DEFAULT_FRAME_RATE:
            segment = segment.set_frame_rate(DEFAULT_FRAME_RATE)
        self._segment = segment
        return self._segment
