import sys

from tqdm import tqdm

DEFAULT_FRAME_RATE = 44100

# Extensions tried when a file referenced by a chart doesn't exist as written, in order of preference
AUDIO_EXTENSIONS = ('.wav', '.ogg', '.flac', '.mp3')
IMAGE_EXTENSIONS = ('.bmp', '.png', '.jpg', '.jpeg', '.gif')


class _StageTqdm(tqdm):
    """Shows the time left while a stage runs, and how long it took once it is done."""
    running_format = '{desc:>36} @ {percentage:>3.0f}% [left {remaining:>5}] [{n:>6}/{total:>6}]|{bar}|'
    finished_format = '{desc:>36} @ {percentage:>3.0f}% [took {elapsed:>5}] [{n:>6}/{total:>6}]|{bar}|'

    def close(self):
        if not self.disable:
            self.bar_format = self.finished_format
        super().close()


def standard_tqdm(*args, **kwargs):
    return _StageTqdm(*args,
                      bar_format=_StageTqdm.running_format,
                      file=sys.stdout,  # Not sure why tqdm outputs to stderr by default
                      **kwargs)


def normalize_chart_path(file_path):
    """Charts are mostly made on Windows, so paths in them may use backslashes"""
    return file_path.strip().replace('\\', '/')


def warn(message):
    # Warnings stay visible even when non-verbose mode silences regular output
    print('Warning: {}'.format(message), file=sys.__stderr__, flush=True)


class Keys(object):
    KEY_1 = 0
    KEY_2 = 1
    KEY_3 = 2
    KEY_4 = 3
    KEY_5 = 4
    KEY_6 = 5
    KEY_7 = 6
    SCRATCH = 7
    NONE = 8

    KEYS = {
        '1': 'KEY_1',
        '2': 'KEY_2',
        '3': 'KEY_3',
        '4': 'KEY_4',
        '5': 'KEY_5',
        '6': 'KEY_6',
        '7': 'KEY_7',
        'S': 'SCRATCH',
        'X': 'NONE'
    }

    # Etterna's "bm-single7": 7 keys with the scratch stored as the last column
    BEATMANIA_7K_KEYS = '1234567S'
    BEATMANIA_7K_MODE = 'bm-single7'

    META = {
        4: 'dance-single',
        5: 'pump-single',
        6: 'dance-solo',
        7: 'kb7-single',
        8: 'dance-double',
        10: 'pump-double'
    }


class Representations(object):
    NOTHING = '0'
    TAP = '1'
    LN_START = '2'
    LN_END = '3'
    MINE = 'M'
