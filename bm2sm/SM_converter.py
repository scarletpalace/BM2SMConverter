import operator
from functools import partial
from typing import Any, Dict, List

from tqdm import tqdm

from bm2sm.data_structures import NotefieldObject
from bm2sm.definitions import IMAGE_EXTENSIONS, Keys, Representations, normalize_chart_path, standard_tqdm, warn
from bm2sm.exceptions import EmptyChart, UnsupportedGameMode
from modules.additional_functions import lcm
from modules.decorators import transform_args
from modules.fake_types import CastableToInt, NonNegativeInt


def escape_sm_text(text):
    """Escape characters that SM files use as delimiters, e.g. in "obj:nickname" credited in the artist field"""
    for character in ('\\', ':', ';', '#'):
        text = text.replace(character, '\\' + character)
    return text


class SMChartConverter(object):
    """A class composing the SM chart."""
    _SM_format = """#TITLE:{title};
#SUBTITLE:{subtitle};
#ARTIST:{artist};
#CREDIT:{credit};
#MUSIC:{audio_name};
#SELECTABLE:YES;
#BANNER:{banner};
#BACKGROUND:{bg};
#GENRE:{genre};
#CDTITLE:;
#OFFSET:0.0000000;
#BPMS:{BPM_changes};
#STOPS:{stops};
#TOTAL:{total};
#JUDGERANK:{judge_rank};
{defexrank}#NOTES:
{game_mode}:
:
{difficulty_name}:
{difficulty}:
0.000,0.000,0.000,0.000,0.000:
{measures}
;"""
    # Free text fields, which may contain characters that have a meaning in SM files
    _TEXT_FIELDS = ('title', 'subtitle', 'artist', 'credit', 'genre')
    objects = ...  # type: List[NotefieldObject]
    _parent = ...  # type: 'BMChartParser'
    _meta_data = ...  # type: Dict[str, Any]

    def __init__(self, parent, keys):
        self._meta_data = {
            'artist': "Unknown",
            'bg': '',
            'banner': '',
            'credit': '',
            'difficulty': 6,
            # BMS gauge and judge values, which SM has no use for, but are kept for reference.
            #   Missing ones get the values LR2 would use
            'total': None,
            'judge_rank': '2',
            'defexrank': None,
            'difficulty_name': "Edit",
            'genre': '',
            'subtitle': '',
            'title': "Unknown",
        }
        self.objects = []
        self._parent = parent
        # (#BPMS, #STOPS) to write instead of the chart's own timing, when that cannot be kept
        self.timing_override = None

        if keys is None:
            # Native beatmania layout. Its scratch lane is stored last, but displayed on the left
            keys = Keys.BEATMANIA_7K_KEYS
            self._meta_data['game_mode'] = Keys.BEATMANIA_7K_MODE
        else:
            try:
                self._meta_data['game_mode'] = Keys.META[len(keys)]
            except KeyError:
                raise UnsupportedGameMode

        self.keys = [
            getattr(Keys, Keys.KEYS[key])
            for key in keys
        ]

    def compose_chart(self):
        if len(self.objects) == 0:
            raise EmptyChart
        self.objects.sort(key=operator.attrgetter('position'))

        measure_splits = {}

        with standard_tqdm(iterable=self.objects, desc='Composing SM chart manifold') as progress_objects:
            for obj in progress_objects:
                measure = obj.measure
                if measure not in measure_splits:
                    measure_splits[measure] = 4
                cur_split = measure_splits[measure]
                measure_splits[measure] = lcm(cur_split, obj.position.denominator)

        amount_of_measures = max(measure_splits) + 1
        measures = []

        with standard_tqdm(range(amount_of_measures), desc='Filling SM chart with 0') as progress_measures:
            for measure_num in progress_measures:
                length = measure_splits.get(NonNegativeInt(measure_num), 4)
                measures.append(
                    [
                        [
                            Representations.NOTHING
                            for _ in range(len(self.keys))
                        ]
                        for _ in range(length)
                    ]
                )

        with standard_tqdm(iterable=self.objects, desc='Injecting objects into SM chart') as progress_objects:
            for obj in progress_objects:
                measure_split = measure_splits[obj.measure]
                local_position = obj.position.numerator % obj.position.denominator
                scaled_position = local_position * (measure_split //
                                                    obj.position.denominator)

                if obj.key not in self.keys:
                    continue
                relative_position = self.keys.index(obj.key)
                this_measure = measures[obj.measure]

                this_measure[scaled_position][relative_position] = obj.symbol

        row_template = "{}" * len(self.keys)
        notes = "\n,\n".join(
            "\n".join(
                row_template.format(*row)
                for row in measure
            )
            for measure in measures
        )

        audio_out_file = self._parent.OGG_file_name
        defexrank = self._meta_data['defexrank']
        result = self._SM_format.format(**{
            **self._meta_data,
            'total': self._meta_data['total'] or self.default_total(),
            'defexrank': '#DEFEXRANK:{};\n'.format(defexrank) if defexrank else '',
            **{field: escape_sm_text(self._meta_data[field]) for field in self._TEXT_FIELDS},
            'BPM_changes': (self.timing_override or (self._parent.timing_manager.bpm_string, None))[0],
            'stops': (self.timing_override or (None, self._parent.timing_manager.ms_stops_string))[1],
            'measures': notes,
            'audio_name': audio_out_file
        })

        result = result.encode('utf-8', errors='ignore')
        tqdm.write('Writing SM file')
        try:
            with open(self._parent.SM_file_path, 'wb') as f:
                f.write(result)
        except IOError:
            tqdm.write('Error while opening SM file')
            raise

    def make_file_setter(self, field):
        setter = self.make_setter(field)

        def inner(new_value):
            file_path = self._parent.find_chart_file(normalize_chart_path(new_value), IMAGE_EXTENSIONS)
            # A missing image is left out instead of failing the whole conversion
            if file_path is None:
                warn('{} file not found, leaving it out: {}'.format(field, new_value))
                return
            # The file may be renamed when copied, e.g. converted to another format
            setter(self._parent.add_file_to_copy(file_path) or file_path)

        return inner

    def default_total(self):
        """The #TOTAL LR2 uses for charts that don't have one, based on the amount of notes."""
        # Counted on all lanes of the BM chart, whatever the key mapping, with a long note counting once
        notes = sum(1 for T in self.objects if T.symbol in (Representations.TAP, Representations.LN_START))
        if notes < 400:
            total = notes / 5 + 200
        elif notes < 600:
            total = (notes - 400) / 2.5 + 280
        else:
            total = (notes - 600) / 5 + 360
        return int(total * 0.8)

    def make_number_setter(self, field, header):
        """Create a setter for a numeric metadata `field` read from `header`, which ignores values that aren't numbers"""
        setter = self.make_setter(field)

        def inner(new_value):
            new_value = new_value.strip()
            try:
                float(new_value)
            except ValueError:
                warn('Ignoring #{} that is not a number: {}'.format(header, new_value))
                return
            setter(new_value)

        return inner

    def make_setter(self, field):
        """Create a setter for a metadata `field`"""
        return partial(operator.setitem, self._meta_data, field)

    @transform_args(..., CastableToInt)
    def set_difficulty(self, difficulty):
        """Set the difficulty from a BM #DIFFICULTY value, 1 (BEGINNER) to 5 (INSANE)"""
        diff_names = (None, "Beginner", "Easy", 'Medium', 'Hard', 'Challenge')
        self._meta_data['difficulty_name'] = diff_names[difficulty]
        self._meta_data['difficulty'] = difficulty

