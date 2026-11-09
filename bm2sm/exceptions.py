class ConversionError(ValueError):
    pass


class LNTypeUnsupportedError(ConversionError):
    pass


class NotPlayer1Error(ConversionError):
    pass


class BPMIsNotDefined(ConversionError):
    pass


class UnsupportedGameMode(ConversionError):
    pass


class EmptyChart(ConversionError):
    pass
