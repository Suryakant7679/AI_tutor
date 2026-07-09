import os
import unittest

from app.llm import gemini_models_to_try, parse_chat_completion_stream_event, parse_gemini_stream_event
from app.main import artifact_category, iter_stream_chunks, parse_json_body, parse_multipart_files, safe_filename


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


class UploadParsingTests(unittest.TestCase):
    def test_multipart_upload_extracts_file(self) -> None:
        boundary = "----aios-test"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="files"; filename="notes.txt"\r\n'
            "Content-Type: text/plain\r\n\r\n"
            "hello upload\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        files = parse_multipart_files(f"multipart/form-data; boundary={boundary}", body)
        self.assertEqual(files[0]["filename"], "notes.txt")
        self.assertEqual(files[0]["content"], b"hello upload")

    def test_safe_filename_removes_unsafe_characters(self) -> None:
        self.assertEqual(safe_filename("../bad<>name.txt"), "bad-name.txt")

    def test_artifact_category_detects_media(self) -> None:
        self.assertEqual(artifact_category("photo.png", "image/png"), "image")
        self.assertEqual(artifact_category("voice.mp3", "audio/mpeg"), "audio")
        self.assertEqual(artifact_category("paper.pdf", "application/pdf"), "pdf")


if __name__ == "__main__":
    unittest.main()
