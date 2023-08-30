from abc import ABC, abstractmethod, abstractstaticmethod  # noqa


class BaseParser(ABC):
    @abstractstaticmethod
    def parse(stream, encoding=None):
        pass
