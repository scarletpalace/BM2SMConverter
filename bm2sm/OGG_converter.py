import operator
import audioop
from typing import List

from pydub import AudioSegment
from tqdm import tqdm

from bm2sm.data_structures import Sound
from bm2sm.definitions import DEFAULT_FRAME_RATE, standard_tqdm
from bm2sm.exceptions import EmptyChart
from modules.decorators import transform_return
from modules.fake_types import CastableToInt


# Sounds are summed as 32 bit samples scaled down by this much, so that up to this many full volume sounds
#   can overlap without the sum clipping. The sum is clipped once at the end, like a player's output is,
#   which makes the result independent of the order the sounds are added in.
_MIX_HEADROOM = 256


def mix_sounds(sounds, length_in_frames, sample_width, channels):
    """Mix `sounds` (all with the same format) into one track of `length_in_frames`, return its raw data."""
    mix_width = 4
    frame_width = mix_width * channels
    mix = bytearray(length_in_frames * frame_width)

    with standard_tqdm(iterable=sounds, desc='Mixing sounds') as progress_sounds:
        for sound in progress_sounds:
            data = audioop.lin2lin(sound.sound.raw_data, sample_width, mix_width)
            data = audioop.mul(data, mix_width, 1 / _MIX_HEADROOM)
            start = sound.start_time_frames * frame_width
            end = start + len(data)
            mix[start:end] = audioop.add(bytes(mix[start:end]), data, mix_width)

    # Scaling back up clips anything that went over the range, then the samples are converted back
    mix = audioop.mul(bytes(mix), mix_width, _MIX_HEADROOM)
    return audioop.lin2lin(mix, mix_width, sample_width)


class OGGConverter(object):
    """A class where audio baking is done."""

    parent = ...  # type: 'BMChartParser'
    sounds = ...  # type: List[Sound]

    def __init__(self, parent):
        self.parent = parent
        self.sounds = []

    # Every sound is mixed straight into its place in a silent track as long as the song.
    #   Each mix only touches the part of the track the sound covers, so the time it takes
    #   depends on the total length of the sounds rather than on how many overlap.
    #
    # Sounds are only interrupted by a later play of the same #WAV id (see cut_off_retriggered_sounds),
    #   a sound is never interrupted by a different one.
    def bake_audio(self):
        if len(self.sounds) == 0:
            raise EmptyChart
        self.sync_everything()
        self.cut_off_retriggered_sounds()

        song_length_in_frames = self.get_song_length_in_frames()

        common_sound = self.sounds[0].sound
        sample_width = common_sound.sample_width
        channels = common_sound.channels

        result = mix_sounds(self.sounds, song_length_in_frames, sample_width, channels)

        tqdm.write('Writing OGG file')
        output = AudioSegment(data=bytes(result),
                              channels=channels,
                              frame_rate=DEFAULT_FRAME_RATE,
                              sample_width=sample_width)

        output.export(self.parent.OGG_file_path,
                      format='ogg')

    @transform_return(CastableToInt)
    def get_song_length_in_frames(self):
        last_sound = max(self.sounds,
                         key=operator.attrgetter('end_time_frames'))
        return last_sound.end_time_frames

    # Reference: "Whenever next aaa.wav is sounded, the sound of previous aaa.wav is interrupted."
    #   So the same #WAV id played several times on one row sounds only once,
    #   and a replay cuts the previous one off. Different ids pointing to the same file still stack.
    # noinspection PyProtectedMember
    def cut_off_retriggered_sounds(self):
        by_id = {}
        for sound in self.sounds:
            by_id.setdefault(sound.wav_id, []).append(sound)

        kept_sounds = []
        for same_id_sounds in by_id.values():
            same_id_sounds.sort(key=operator.attrgetter('start_time_frames'))
            for sound, next_sound in zip(same_id_sounds, same_id_sounds[1:] + [None]):
                if next_sound is None or sound.end_time_frames <= next_sound.start_time_frames:
                    kept_sounds.append(sound)
                    continue
                frames_left = next_sound.start_time_frames - sound.start_time_frames
                if frames_left <= 0:
                    continue
                segment = sound.sound
                sound.sound = segment._spawn(segment.raw_data[:frames_left * segment.frame_width])
                kept_sounds.append(sound)

        self.sounds = kept_sounds

    # noinspection PyProtectedMember
    def sync_everything(self):
        data = [(T, T.sound) for T in self.sounds]
        sound, segments = zip(*data)

        # Regular syncing creates copies of the sound
        #   And this is slow as hell
        # So a small hack is used as a workaround
        synced_segments = AudioSegment._sync(*segments)
        result = zip(sound, synced_segments)
        for sound, synced_segment in result:
            sound.sound = synced_segment
