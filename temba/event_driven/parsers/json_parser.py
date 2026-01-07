import json

from .base_parser import BaseParser
from .exceptions import ParseError


class JSONParser(BaseParser):
    @staticmethod
    def parse(stream, encoding="utf-8"):
        """
        Parses the incoming bytestream (or string) as JSON and returns the resulting data.
        """

        if not stream:
            raise ParseError("JSON parse error - stream cannot be empty")

        try:
            if isinstance(stream, str):
                decoded_stream = stream
            elif isinstance(stream, (bytes, bytearray, memoryview)):
                decoded_stream = bytes(stream).decode(encoding)
            else:
                raise ParseError(f"JSON parse error - unsupported stream type: {type(stream).__name__}")

            return json.loads(decoded_stream)
        except ValueError as exc:
            raise ParseError("JSON parse error - %s" % str(exc))
