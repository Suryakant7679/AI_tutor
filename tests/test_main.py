import os
import unittest

from app.llm import gemini_models_to_try, parse_chat_completion_stream_event, parse_gemini_stream_event
from app.main import iter_stream_chunks, parse_json_body


class ParseJsonBodyTests(unittest.TestCase):
    def test_empty_body_defaults_to_empty_dict(self) -> None:
        self.assertEqual(parse_json_body(""), {})

    def test_valid_json_is_parsed(self) -> None:
        self.assertEqual(parse_json_body('{"message": "hello"}'), {"message": "hello"})

    def test_invalid_json_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            parse_json_body("{not valid json}")

    def test_form_encoded_body_is_parsed(self) -> None:
        self.assertEqual(parse_json_body("message=Hello&stream=true"), {"message": "Hello", "stream": "true"})


class StreamingParserTests(unittest.TestCase):
    def test_chat_completion_stream_event_extracts_delta_text(self) -> None:
        event = '{"choices":[{"delta":{"content":"hello"}}]}'
        self.assertEqual(parse_chat_completion_stream_event(event, "groq"), "hello")

    def test_chat_completion_stream_event_allows_empty_delta(self) -> None:
        event = '{"choices":[{"delta":{"role":"assistant"}}]}'
        self.assertEqual(parse_chat_completion_stream_event(event, "groq"), "")

    def test_gemini_stream_event_extracts_text_parts(self) -> None:
        event = '{"candidates":[{"content":{"parts":[{"text":"hello "},{"text":"there"}]}}]}'
        self.assertEqual(parse_gemini_stream_event(event, "gemini-2.0-flash"), "hello there")

    def test_gemini_stream_event_allows_empty_parts(self) -> None:
        event = '{"candidates":[{"content":{"parts":[]}}]}'
        self.assertEqual(parse_gemini_stream_event(event, "gemini-2.0-flash"), "")


class GeminiModelFallbackTests(unittest.TestCase):
    def test_default_gemini_model_is_current(self) -> None:
        old_value = os.environ.pop("AIOS_GEMINI_MODEL", None)
        old_default = os.environ.pop("AIOS_DEFAULT_MODEL", None)
        try:
            self.assertEqual(gemini_models_to_try()[0], "gemini-2.0-flash")
        finally:
            if old_value is not None:
                os.environ["AIOS_GEMINI_MODEL"] = old_value
            if old_default is not None:
                os.environ["AIOS_DEFAULT_MODEL"] = old_default


class StreamingChunkingTests(unittest.TestCase):
    def test_large_stream_chunks_are_split_for_incremental_updates(self) -> None:
        self.assertEqual(list(iter_stream_chunks(["hello world"], chunk_size=5)), ["hello", " worl", "d"])


if __name__ == "__main__":
    unittest.main()
