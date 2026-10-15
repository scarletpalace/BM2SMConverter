"""Resolving of BM control flow (#RANDOM, #IF, #SWITCH and friends) into a plain chart.

Stepmania has no way to represent random charts, so a random value is picked for every
#RANDOM/#SWITCH and only the lines of the chosen branches are kept.
"""

from re import IGNORECASE, compile as compile_regex

# Longer keywords go first, so that e.g. #ENDIF is not read as #END
_KEYWORD_REGEX = compile_regex(
    r'\s*#(SETRANDOM|RANDOM|RONDAM|ENDRANDOM|ELSEIF|ELSE|ENDIF|END IF|END|IF|'
    r'SETSWITCH|SWITCH|CASE|SKIP|DEF|ENDSW)(?=\s|$)\s*(\S*)',
    IGNORECASE
)


def _to_int(value):
    try:
        return int(value)
    except ValueError:
        return 0


class _RandomFrame(object):
    def __init__(self, value):
        self.value = value
        # Lines directly inside #RANDOM but outside of any #IF are always interpreted
        self.active = True


class _IfFrame(object):
    def __init__(self, matched):
        self.matched = matched
        self.active = matched


class _SwitchFrame(object):
    def __init__(self, value):
        self.value = value
        self.state = 'searching'  # -> 'running' at the matching #CASE/#DEF -> 'done' at #SKIP

    @property
    def active(self):
        return self.state == 'running'


def resolve_control_flow(lines, rng):
    """Return the lines of the branches chosen with `rng` and the amount of random values that were generated."""
    result = []
    frames = []
    randoms_generated = 0

    def is_active():
        return all(frame.active for frame in frames)

    def current_random_value():
        for frame in reversed(frames):
            if isinstance(frame, _RandomFrame):
                return frame.value
        return None

    def close_nested_randoms():
        # A nested #RANDOM without #ENDRANDOM ends together with the #IF block it is in
        if any(isinstance(frame, _IfFrame) for frame in frames):
            while isinstance(frames[-1], _RandomFrame):
                frames.pop()

    def pop_until(frame_type):
        while frames and not isinstance(frames[-1], frame_type):
            frames.pop()
        if frames:
            frames.pop()

    for line in lines:
        keyword_match = _KEYWORD_REGEX.match(line)
        if not keyword_match:
            if is_active():
                result.append(line)
            continue

        keyword = keyword_match.group(1).upper()
        argument = keyword_match.group(2)

        if keyword in ('RANDOM', 'RONDAM', 'SETRANDOM'):
            if keyword == 'SETRANDOM':
                value = _to_int(argument)
            else:
                value = rng.randint(1, max(1, _to_int(argument)))
                randoms_generated += 1
            if frames and isinstance(frames[-1], _RandomFrame):
                # #ENDRANDOM is commonly omitted, so a #RANDOM outside of any #IF replaces the current one
                frames[-1].value = value
            else:
                frames.append(_RandomFrame(value))

        elif keyword == 'ENDRANDOM':
            pop_until(_RandomFrame)

        elif keyword == 'IF':
            frames.append(_IfFrame(_to_int(argument) == current_random_value()))

        elif keyword in ('ELSEIF', 'ELSE'):
            close_nested_randoms()
            if frames and isinstance(frames[-1], _IfFrame):
                frame = frames[-1]
                matches = keyword == 'ELSE' or _to_int(argument) == current_random_value()
                frame.active = not frame.matched and matches
                frame.matched = frame.matched or frame.active

        elif keyword in ('ENDIF', 'END IF', 'END'):
            close_nested_randoms()
            if frames and isinstance(frames[-1], _IfFrame):
                frames.pop()

        elif keyword in ('SWITCH', 'SETSWITCH'):
            if keyword == 'SETSWITCH':
                value = _to_int(argument)
            else:
                value = rng.randint(1, max(1, _to_int(argument)))
                randoms_generated += 1
            frames.append(_SwitchFrame(value))

        elif keyword in ('CASE', 'DEF', 'SKIP'):
            if frames and isinstance(frames[-1], _SwitchFrame):
                frame = frames[-1]
                # A case falls through into the next one until #SKIP, like in C
                if keyword == 'SKIP':
                    if frame.state == 'running':
                        frame.state = 'done'
                elif frame.state == 'searching' and (keyword == 'DEF' or _to_int(argument) == frame.value):
                    frame.state = 'running'

        elif keyword == 'ENDSW':
            pop_until(_SwitchFrame)

    return result, randoms_generated
