import os
import tempfile
import unittest
from pathlib import Path

from app.llm import gemini_models_to_try, parse_chat_completion_stream_event, parse_gemini_stream_event
from app.main import (
    artifact_category,
    browser_results_context_text,
    build_context_messages,
    compact_conversations,
    compress_context_text,
    conversation_messages_for_llm,
    count_message_tokens,
    chunk_document_text,
    clean_extracted_text,
    add_citations_to_results,
    developer_instructions_context_text,
    document_metadata_for_upload,
    estimate_tokens,
    extract_pdf_text_basic,
    extract_pdf_text_pymupdf,
    fit_messages_to_token_window,
    generate_embedding,
    git_status_context_text,
    hybrid_retrieve,
    iter_stream_chunks,
    load_artifacts,
    load_vector_records,
    long_term_memory_context_text,
    mcp_outputs_context_text,
    open_files_context_text,
    parse_json_body,
    parse_multipart_files,
    project_context_text,
    rank_context_sections,
    remove_duplicate_context_sections,
    related_conversations,
    retrieved_context_text,
    rerank_results,
    running_task_state_context_text,
    safe_filename,
    select_top_k,
    short_term_memory_context_text,
    similar_documents,
    usable_extracted_text,
    save_artifacts,
    semantic_search,
    terminal_output_context_text,
    upsert_vector_records,
    uploaded_files_context_text,
    user_preferences_context_text,
    vector_record_for_message,
    vector_records_for_artifact,
    vector_records_for_long_term_memory,
)
from app.store import ConversationStore


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


class SessionStoreTests(unittest.TestCase):
    def test_session_is_created_and_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(os.path.join(temp_dir, "conversations.json"))
            session = store.get_or_create_session()
            self.assertEqual(store.get_or_create_session(session["id"])["id"], session["id"])

    def test_conversations_can_be_scoped_to_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(os.path.join(temp_dir, "conversations.json"))
            first = store.get_or_create_session()
            second = store.get_or_create_session()
            first_conversation = store.create_conversation(session_id=first["id"])
            store.create_conversation(session_id=second["id"])

            scoped = store.list_conversations_for_session(first["id"])
            self.assertEqual([item["id"] for item in scoped], [first_conversation["id"]])

    def test_compact_conversations_includes_session_id(self) -> None:
        conversation = {
            "id": "conversation-1",
            "session_id": "session-1",
            "title": "New chat",
            "created_at": "now",
            "updated_at": "now",
            "messages": [],
        }
        self.assertEqual(compact_conversations([conversation])[0]["session_id"], "session-1")

    def test_session_tracks_active_project_and_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(os.path.join(temp_dir, "conversations.json"))
            session = store.get_or_create_session()

            updated = store.update_session_context(
                session["id"],
                active_project="AI Tutor",
                current_workspace={"name": "AI Tutor", "focus": "Checkpoint 6"},
                running_task="Add tracking",
                active_file="app/store.py",
                active_tool="editor",
                terminal_output="pytest ok",
                browser_results="Result: docs page",
                mcp_outputs="filesystem result",
                developer_instructions="Prefer small patches",
            )

            self.assertEqual(updated["active_project"], "AI Tutor")
            self.assertEqual(updated["current_workspace"]["name"], "AI Tutor")
            self.assertEqual(updated["current_workspace"]["focus"], "Checkpoint 6")
            self.assertEqual(updated["running_task"], "Add tracking")
            self.assertEqual(updated["active_file"], "app/store.py")
            self.assertEqual(updated["active_tool"], "editor")
            self.assertEqual(updated["terminal_output"], "pytest ok")
            self.assertEqual(updated["browser_results"], "Result: docs page")
            self.assertEqual(updated["mcp_outputs"], "filesystem result")
            self.assertEqual(updated["developer_instructions"], "Prefer small patches")

    def test_session_tracks_user_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(os.path.join(temp_dir, "conversations.json"))
            session = store.get_or_create_session()

            updated = store.update_session_context(
                session["id"],
                user_preferences={
                    "provider_mode": "gemini",
                    "compact_mode": True,
                    "context_window_tokens": 12000,
                },
            )

            self.assertEqual(updated["user_preferences"]["provider_mode"], "gemini")
            self.assertTrue(updated["user_preferences"]["compact_mode"])
            self.assertEqual(updated["user_preferences"]["context_window_tokens"], 12000)

    def test_long_term_memory_survives_across_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(os.path.join(temp_dir, "conversations.json"))
            first = store.get_or_create_session()
            store.update_session_context(
                first["id"],
                active_project="AI Tutor",
                current_workspace={"name": "AI Tutor", "focus": "Memory"},
                terminal_output="PS> python -m unittest",
                developer_instructions="Prefer small functions",
                user_preferences={"compact_mode": True},
            )
            store.get_or_create_session()

            memory = store.get_long_term_memory()
            self.assertTrue(memory["user_preferences"]["compact_mode"])
            self.assertEqual(memory["projects"][0]["name"], "AI Tutor")
            self.assertIn("python -m unittest", memory["commands"])
            self.assertIn("Prefer small functions", memory["coding_style"])

    def test_explicit_learned_behavior_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(os.path.join(temp_dir, "conversations.json"))
            store.update_long_term_memory(learned_behavior=["Explain changes concisely"])
            self.assertIn("Explain changes concisely", store.get_long_term_memory()["learned_behavior"])

    def test_long_term_memory_is_rendered_for_model_context(self) -> None:
        context = long_term_memory_context_text({
            "user_preferences": {"compact_mode": True},
            "coding_style": ["Use type hints"],
            "projects": [{"name": "AI Tutor", "focus": "Memory"}],
            "commands": ["python -m unittest"],
            "learned_behavior": ["Prefer concise answers"],
        })
        self.assertIn("Use type hints", context)
        self.assertIn("AI Tutor", context)
        self.assertIn("python -m unittest", context)
        self.assertIn("Prefer concise answers", context)

    def test_conversation_threads_scope_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(os.path.join(temp_dir, "conversations.json"))
            conversation = store.create_conversation()
            thread = store.create_thread(conversation["id"], "Branch")
            store.add_message(conversation["id"], "user", "main message", thread_id="main")
            store.add_message(conversation["id"], "user", "branch message", thread_id=thread["id"])

            saved = store.get_conversation(conversation["id"])
            branch_messages = [
                item["content"]
                for item in saved["messages"]
                if item["thread_id"] == thread["id"]
            ]
            self.assertEqual(branch_messages, ["branch message"])

    def test_conversation_summary_and_compression_are_refreshed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(os.path.join(temp_dir, "conversations.json"))
            conversation = store.create_conversation()
            for index in range(8):
                store.add_message(conversation["id"], "user", f"message {index}")

            saved = store.get_conversation(conversation["id"])
            self.assertGreater(saved["compressed_message_count"], 0)
            self.assertIn("message", saved["summary"])

    def test_short_term_memory_tracks_conversation_files_task_variables_and_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(os.path.join(temp_dir, "conversations.json"))
            conversation = store.create_conversation()
            store.add_message(conversation["id"], "user", "Summarize the attached paper")

            memory = store.update_short_term_memory(
                conversation["id"],
                artifact_ids=["paper-1"],
                task="Summarize research",
                variables={"audience": "beginner"},
                tool_outputs={"terminal": "extraction complete"},
            )

            self.assertEqual(memory["artifact_ids"], ["paper-1"])
            self.assertEqual(memory["task"], "Summarize research")
            self.assertEqual(memory["variables"]["audience"], "beginner")
            self.assertEqual(memory["tool_outputs"]["terminal"], "extraction complete")
            self.assertEqual(memory["recent_messages"][-1]["content"], "Summarize the attached paper")

            remembered = store.update_short_term_memory(conversation["id"])
            self.assertEqual(remembered["artifact_ids"], ["paper-1"])

    def test_short_term_memory_is_added_to_prompt_context(self) -> None:
        memory = {
            "task": "Debug upload",
            "variables": {"file": "paper.pdf"},
            "tool_outputs": {"terminal": "HTTP 201"},
        }
        context = short_term_memory_context_text(memory)
        self.assertIn("Debug upload", context)
        self.assertIn("paper.pdf", context)
        self.assertIn("HTTP 201", context)


class ContextWindowTests(unittest.TestCase):
    def test_estimate_tokens_counts_words_and_punctuation(self) -> None:
        self.assertGreaterEqual(estimate_tokens("hello, world!"), 3)

    def test_context_messages_are_pruned_to_token_budget(self) -> None:
        messages = [
            {"role": "user", "content": "older " * 100},
            {"role": "assistant", "content": "middle response"},
            {"role": "user", "content": "latest question"},
        ]
        selected = conversation_messages_for_llm(messages, max_tokens=30)

        self.assertEqual(selected[-1]["content"], "latest question")
        self.assertLessEqual(count_message_tokens(selected), 30)

    def test_context_can_be_filtered_by_thread_and_include_summary(self) -> None:
        messages = [
            {"role": "user", "thread_id": "main", "content": "main message"},
            {"role": "user", "thread_id": "branch", "content": "branch message"},
        ]
        selected = conversation_messages_for_llm(
            messages,
            max_tokens=200,
            thread_id="branch",
            summary="Older useful facts.",
        )

        self.assertEqual(selected[0]["role"], "system")
        self.assertEqual(selected[-1]["content"], "branch message")
        self.assertNotIn("main message", [item["content"] for item in selected])

    def test_project_context_is_rendered_from_session(self) -> None:
        session = {
            "active_project": "AI Tutor",
            "current_workspace": {"name": "AI Tutor", "focus": "Checkpoint 8"},
            "running_task": "Build context",
            "active_tool": "chat",
        }

        context = project_context_text(session)

        self.assertIn("Active project: AI Tutor", context)
        self.assertIn("Running task: Build context", context)

    def test_open_files_context_reads_workspace_file(self) -> None:
        context = open_files_context_text({"active_file": "readme.md", "open_files": []})

        self.assertIn("readme.md", context)
        self.assertIn("AI Tutor", context)

    def test_context_builder_prepends_structured_context(self) -> None:
        session = {
            "active_project": "AI Tutor",
            "current_workspace": {"name": "AI Tutor", "focus": "Checkpoint 8"},
            "running_task": "",
            "active_tool": "",
            "active_file": "",
            "open_files": [],
            "terminal_output": "tests passed",
            "browser_results": "official docs result",
            "mcp_outputs": "tool output",
            "developer_instructions": "keep changes small",
            "user_preferences": {"provider_mode": "auto", "compact_mode": False, "context_window_tokens": 4000},
        }
        messages = [{"role": "user", "content": "hello"}]

        built = build_context_messages(session, messages, max_tokens=4000)

        self.assertEqual(built[0]["role"], "system")
        self.assertIn("Current project context", built[0]["content"])
        self.assertIn("Recent terminal output", built[0]["content"])
        self.assertIn("Browser results", built[0]["content"])
        self.assertIn("MCP outputs", built[0]["content"])
        self.assertIn("Developer instructions", built[0]["content"])
        self.assertIn("User preferences", built[0]["content"])

    def test_terminal_output_context_is_rendered(self) -> None:
        context = terminal_output_context_text({"terminal_output": "python -m unittest\nOK"})

        self.assertIn("Recent terminal output", context)
        self.assertIn("OK", context)

    def test_browser_results_context_is_rendered(self) -> None:
        context = browser_results_context_text({"browser_results": "Search result summary"})

        self.assertIn("Browser results", context)
        self.assertIn("Search result summary", context)

    def test_git_status_context_is_available(self) -> None:
        context = git_status_context_text()

        self.assertIn("Git status", context)

    def test_mcp_outputs_context_is_rendered(self) -> None:
        context = mcp_outputs_context_text({"mcp_outputs": "tool result"})

        self.assertIn("MCP outputs", context)
        self.assertIn("tool result", context)

    def test_running_task_state_context_is_rendered(self) -> None:
        context = running_task_state_context_text(
            {"running_task": "Build context", "active_file": "app/main.py", "active_tool": "editor"}
        )

        self.assertIn("Running task state", context)
        self.assertIn("Build context", context)

    def test_developer_instructions_context_is_rendered(self) -> None:
        context = developer_instructions_context_text({"developer_instructions": "Prefer tests"})

        self.assertIn("Developer instructions", context)
        self.assertIn("Prefer tests", context)

    def test_user_preferences_context_is_rendered(self) -> None:
        context = user_preferences_context_text(
            {"user_preferences": {"provider_mode": "gemini", "compact_mode": True, "context_window_tokens": 12000}}
        )

        self.assertIn("User preferences", context)
        self.assertIn("gemini", context)

    def test_context_sections_are_ranked_by_priority(self) -> None:
        ranked = rank_context_sections(
            [
                {"name": "low", "priority": 1, "text": "low"},
                {"name": "high", "priority": 10, "text": "high"},
            ]
        )

        self.assertEqual([item["name"] for item in ranked], ["high", "low"])

    def test_duplicate_context_sections_are_removed(self) -> None:
        unique = remove_duplicate_context_sections(
            [
                {"name": "one", "priority": 2, "text": "Same text"},
                {"name": "two", "priority": 1, "text": " same   text "},
            ]
        )

        self.assertEqual(len(unique), 1)

    def test_context_text_is_compressed(self) -> None:
        compressed = compress_context_text("word " * 500, max_tokens=40)

        self.assertIn("Context compressed", compressed)
        self.assertLess(estimate_tokens(compressed), 120)

    def test_context_builder_fits_target_window(self) -> None:
        session = {
            "developer_instructions": "important " * 300,
            "active_project": "AI Tutor",
            "current_workspace": {"name": "AI Tutor", "focus": "Checkpoint 8"},
            "running_task": "Fit context",
            "active_file": "",
            "open_files": [],
            "terminal_output": "terminal " * 300,
            "browser_results": "browser " * 300,
            "mcp_outputs": "mcp " * 300,
            "user_preferences": {"provider_mode": "auto", "compact_mode": False, "context_window_tokens": 500},
        }
        messages = [{"role": "user", "content": "latest question"}]

        built = build_context_messages(session, messages, max_tokens=500)

        self.assertLessEqual(count_message_tokens(built), 500)
        self.assertEqual(built[-1]["content"], "latest question")

    def test_message_fitting_preserves_system_and_latest_message(self) -> None:
        fitted = fit_messages_to_token_window(
            [
                {"role": "system", "content": "system context"},
                {"role": "user", "content": "old " * 200},
                {"role": "user", "content": "latest"},
            ],
            max_tokens=80,
        )

        self.assertEqual(fitted[0]["role"], "system")
        self.assertEqual(fitted[-1]["content"], "latest")


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

    def test_artifact_category_detects_documents(self) -> None:
        self.assertEqual(artifact_category("report.docx", "application/octet-stream"), "document")

    def test_document_upload_extracts_text_preview(self) -> None:
        metadata = document_metadata_for_upload(
            "notes.txt",
            "text/plain",
            b"hello   document-\nupload\n\n\nsecond line",
            Path("notes.txt"),
        )

        self.assertEqual(metadata["ocr_status"], "not_required")
        self.assertEqual(metadata["extracted_text"], "hello documentupload\n\nsecond line")
        self.assertEqual(metadata["preview"], "hello documentupload\n\nsecond line")
        self.assertEqual(metadata["metadata"]["word_count"], 4)
        self.assertEqual(metadata["metadata"]["chunk_count"], 1)
        self.assertEqual(metadata["chunks"][0]["index"], 0)

    def test_text_cleaning_normalizes_ocr_noise(self) -> None:
        cleaned = clean_extracted_text("Alpha   beta-\ngamma \n\n\n delta , ok")

        self.assertEqual(cleaned, "Alpha betagamma\n\ndelta, ok")

    def test_document_text_is_chunked_with_metadata(self) -> None:
        chunks = chunk_document_text("Sentence one. " * 80, chunk_size=220, overlap=30)

        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0]["id"], "chunk-0001")
        self.assertGreater(chunks[0]["word_count"], 0)

    def test_embedding_generation_is_deterministic_and_normalized(self) -> None:
        first = generate_embedding("alpha beta beta", dimensions=16)
        second = generate_embedding("alpha beta beta", dimensions=16)
        magnitude = sum(value * value for value in first) ** 0.5

        self.assertEqual(first, second)
        self.assertEqual(len(first), 16)
        self.assertAlmostEqual(magnitude, 1.0, places=5)

    def test_vector_records_are_created_for_document_chunks(self) -> None:
        artifact = {
            "id": "artifact-1",
            "filename": "notes.txt",
            "category": "file",
            "content_type": "text/plain",
            "document_type": "text",
            "path": "data/uploads/artifact-1-notes.txt",
            "chunks": chunk_document_text("alpha beta gamma"),
        }

        records = vector_records_for_artifact(artifact)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["artifact_id"], "artifact-1")
        self.assertEqual(len(records[0]["embedding"]), 64)

    def test_conversation_messages_and_long_term_memories_are_embedded(self) -> None:
        message_record = vector_record_for_message(
            "conversation-1",
            {"id": "message-1", "role": "user", "content": "Remember rotary embeddings", "thread_id": "main"},
        )
        memory_records = vector_records_for_long_term_memory({
            "coding_style": ["Prefer type hints"],
            "projects": [{"name": "AI Tutor", "focus": "semantic memory"}],
            "commands": [], "learned_behavior": [], "user_preferences": {},
        })

        self.assertEqual(message_record["source_type"], "conversation")
        self.assertEqual(len(message_record["embedding"]), 64)
        self.assertTrue(all(record["source_type"] == "memory" for record in memory_records))
        self.assertGreaterEqual(len(memory_records), 2)

    def test_semantic_search_spans_documents_and_conversations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from app import main as main_module
            old_index = main_module.VECTOR_INDEX
            main_module.VECTOR_INDEX = main_module.Path(temp_dir) / "vectors.json"
            try:
                main_module.save_vector_records([
                    {
                        "id": "doc:1", "source_type": "document", "artifact_id": "doc",
                        "filename": "vectors.pdf", "document_type": "pdf",
                        "text": "Global word vectors encode semantic relationships.",
                        "embedding": generate_embedding("Global word vectors encode semantic relationships."),
                        "metadata": {},
                    },
                    {
                        "id": "conversation:1", "source_type": "conversation", "source_id": "chat",
                        "filename": "conversation-chat", "document_type": "conversation",
                        "text": "We discussed railway ticket reservations.",
                        "embedding": generate_embedding("We discussed railway ticket reservations."),
                        "metadata": {},
                    },
                ])
                all_results = semantic_search("semantic word vectors", top_k=2)
                conversation_results = semantic_search("railway reservations", top_k=2, source_types=["conversation"])
            finally:
                main_module.VECTOR_INDEX = old_index

        self.assertEqual(all_results[0]["source_type"], "document")
        self.assertEqual([item["source_type"] for item in conversation_results], ["conversation"])

    def test_related_conversations_are_grouped_and_exclude_current_chat(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from app import main as main_module
            old_index = main_module.VECTOR_INDEX
            main_module.VECTOR_INDEX = main_module.Path(temp_dir) / "vectors.json"
            conversations = [
                {"id": "current", "title": "Current", "messages": [], "updated_at": "now"},
                {"id": "related", "title": "Embedding discussion", "messages": [], "updated_at": "now"},
                {"id": "other", "title": "Travel", "messages": [], "updated_at": "now"},
            ]
            try:
                main_module.save_vector_records([
                    vector_record_for_message("current", {"id": "m1", "role": "user", "content": "semantic embeddings"}),
                    vector_record_for_message("related", {"id": "m2", "role": "user", "content": "semantic vector embeddings for memory"}),
                    vector_record_for_message("other", {"id": "m3", "role": "user", "content": "railway ticket travel"}),
                ])
                results = related_conversations("semantic vector embeddings", conversations, exclude_id="current")
            finally:
                main_module.VECTOR_INDEX = old_index

        self.assertEqual(results[0]["conversation_id"], "related")
        self.assertNotIn("current", [item["conversation_id"] for item in results])

    def test_similar_documents_rank_related_chunk_embeddings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from app import main as main_module
            old_index = main_module.VECTOR_INDEX
            main_module.VECTOR_INDEX = main_module.Path(temp_dir) / "vectors.json"
            try:
                def record(artifact_id, chunk_id, filename, text):
                    return {
                        "id": f"{artifact_id}:{chunk_id}", "source_type": "document",
                        "artifact_id": artifact_id, "chunk_id": chunk_id, "filename": filename,
                        "document_type": "pdf", "text": text, "embedding": generate_embedding(text),
                        "metadata": {},
                    }
                main_module.save_vector_records([
                    record("source", "c1", "source.pdf", "neural word embeddings semantic vectors"),
                    record("similar", "c1", "similar.pdf", "semantic word vectors and neural embeddings"),
                    record("different", "c1", "different.pdf", "railway reservation passenger ticket"),
                ])
                results = similar_documents("source", top_k=2)
            finally:
                main_module.VECTOR_INDEX = old_index

        self.assertEqual(results[0]["artifact_id"], "similar")
        self.assertGreater(results[0]["score"], results[1]["score"])
        self.assertTrue(results[0]["matching_chunks"])

    def test_vector_records_are_upserted_to_json_store(self) -> None:
        old_vector_index = os.environ.get("AIOS_VECTOR_INDEX")
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["AIOS_VECTOR_INDEX"] = os.path.join(temp_dir, "vectors.json")
            try:
                from app import main as main_module

                old_index = main_module.VECTOR_INDEX
                main_module.VECTOR_INDEX = main_module.Path(os.environ["AIOS_VECTOR_INDEX"])
                upsert_vector_records(
                    [
                        {
                            "id": "artifact-1:chunk-0001",
                            "artifact_id": "artifact-1",
                            "chunk_id": "chunk-0001",
                            "embedding": [1.0, 0.0],
                        }
                    ]
                )

                records = load_vector_records()
            finally:
                main_module.VECTOR_INDEX = old_index
                if old_vector_index is None:
                    os.environ.pop("AIOS_VECTOR_INDEX", None)
                else:
                    os.environ["AIOS_VECTOR_INDEX"] = old_vector_index

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["id"], "artifact-1:chunk-0001")

    def test_hybrid_retrieval_combines_vectors_and_keywords(self) -> None:
        old_vector_index = os.environ.get("AIOS_VECTOR_INDEX")
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["AIOS_VECTOR_INDEX"] = os.path.join(temp_dir, "vectors.json")
            try:
                from app import main as main_module

                old_index = main_module.VECTOR_INDEX
                main_module.VECTOR_INDEX = main_module.Path(os.environ["AIOS_VECTOR_INDEX"])
                records = [
                    {
                        "id": "a:chunk-0001",
                        "artifact_id": "a",
                        "chunk_id": "chunk-0001",
                        "filename": "algebra-notes.txt",
                        "document_type": "text",
                        "text": "Linear equations use variables and constants.",
                        "embedding": generate_embedding("Linear equations use variables and constants."),
                        "metadata": {"category": "file", "content_type": "text/plain"},
                    },
                    {
                        "id": "b:chunk-0001",
                        "artifact_id": "b",
                        "chunk_id": "chunk-0001",
                        "filename": "history.txt",
                        "document_type": "text",
                        "text": "Ancient trade routes crossed mountains.",
                        "embedding": generate_embedding("Ancient trade routes crossed mountains."),
                        "metadata": {"category": "file", "content_type": "text/plain"},
                    },
                ]
                main_module.save_vector_records(records)

                results = hybrid_retrieve("linear equation variables", top_k=2)
            finally:
                main_module.VECTOR_INDEX = old_index
                if old_vector_index is None:
                    os.environ.pop("AIOS_VECTOR_INDEX", None)
                else:
                    os.environ["AIOS_VECTOR_INDEX"] = old_vector_index

        self.assertEqual(results[0]["id"], "a:chunk-0001")
        self.assertGreater(results[0]["scores"]["hybrid"], results[1]["scores"]["hybrid"])
        self.assertIn("rerank", results[0]["scores"])

    def test_rerank_boosts_exact_phrase_match(self) -> None:
        results = [
            {"id": "low", "filename": "notes.txt", "document_type": "text", "text": "alpha beta", "scores": {"hybrid": 0.5}},
            {"id": "high", "filename": "notes.txt", "document_type": "text", "text": "find exact phrase here", "scores": {"hybrid": 0.4}},
        ]

        reranked = rerank_results("exact phrase", results)

        self.assertEqual(reranked[0]["id"], "high")

    def test_top_k_selection_limits_reranked_results(self) -> None:
        results = [
            {"id": "a", "scores": {"rerank": 0.2}},
            {"id": "b", "scores": {"rerank": 0.9}},
            {"id": "c", "scores": {"rerank": 0.4}},
        ]

        selected = select_top_k(results, top_k=2)

        self.assertEqual([item["id"] for item in selected], ["b", "c"])

    def test_citation_generation_labels_retrieved_chunks(self) -> None:
        cited = add_citations_to_results(
            [
                {
                    "filename": "notes.txt",
                    "chunk_id": "chunk-0002",
                    "metadata": {"start_char": 10, "end_char": 80},
                }
            ]
        )

        self.assertEqual(cited[0]["citation"], "[1] notes.txt, chunk-0002, chars 10-80")

    def test_retrieved_context_is_injected_into_chat_context(self) -> None:
        old_vector_index = os.environ.get("AIOS_VECTOR_INDEX")
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["AIOS_VECTOR_INDEX"] = os.path.join(temp_dir, "vectors.json")
            try:
                from app import main as main_module

                old_index = main_module.VECTOR_INDEX
                main_module.VECTOR_INDEX = main_module.Path(os.environ["AIOS_VECTOR_INDEX"])
                main_module.save_vector_records(
                    [
                        {
                            "id": "a:chunk-0001",
                            "artifact_id": "a",
                            "chunk_id": "chunk-0001",
                            "filename": "algebra-notes.txt",
                            "document_type": "text",
                            "text": "Linear equations use variables and constants.",
                            "embedding": generate_embedding("Linear equations use variables and constants."),
                            "metadata": {"category": "file", "content_type": "text/plain", "start_char": 0, "end_char": 45},
                        }
                    ]
                )
                session = {
                    "active_project": "",
                    "current_workspace": {},
                    "running_task": "",
                    "active_tool": "",
                    "active_file": "",
                    "open_files": [],
                    "terminal_output": "",
                    "browser_results": "",
                    "mcp_outputs": "",
                    "developer_instructions": "",
                    "user_preferences": {"provider_mode": "auto", "compact_mode": False, "context_window_tokens": 4000},
                }

                context = retrieved_context_text("linear equations", top_k=1)
                built = build_context_messages(session, [{"role": "user", "content": "linear equations"}], max_tokens=4000)
            finally:
                main_module.VECTOR_INDEX = old_index
                if old_vector_index is None:
                    os.environ.pop("AIOS_VECTOR_INDEX", None)
                else:
                    os.environ["AIOS_VECTOR_INDEX"] = old_vector_index

        self.assertIn("Retrieved document context", context)
        self.assertIn("[1] algebra-notes.txt, chunk-0001", context)
        self.assertIn("Retrieved document context", built[0]["content"])

    def test_scanned_pdf_without_text_is_marked_for_ocr(self) -> None:
        old_pdf_command = os.environ.pop("AIOS_PDF_OCR_COMMAND", None)
        old_ocr_command = os.environ.pop("AIOS_OCR_COMMAND", None)
        try:
            metadata = document_metadata_for_upload(
                "scan.pdf",
                "application/pdf",
                b"%PDF-1.4\n%%EOF",
                Path("scan.pdf"),
            )
        finally:
            if old_pdf_command is not None:
                os.environ["AIOS_PDF_OCR_COMMAND"] = old_pdf_command
            if old_ocr_command is not None:
                os.environ["AIOS_OCR_COMMAND"] = old_ocr_command

        self.assertEqual(metadata["ocr_status"], "unavailable")
        self.assertTrue(metadata["metadata"]["scanned_candidate"])

    def test_basic_pdf_text_can_be_extracted(self) -> None:
        text = extract_pdf_text_basic(b"%PDF-1.4\nBT (Hello from PDF text) Tj ET\n%%EOF")

        self.assertIn("Hello from PDF text", text)

    def test_binary_pdf_noise_is_not_accepted_as_text(self) -> None:
        self.assertEqual(usable_extracted_text("\x87Íd\x8e \x8bôß\x80óþüôõÕ\x11À9"), "")

    def test_pymupdf_extractor_returns_empty_for_non_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "not-a-pdf.pdf"
            path.write_text("not a pdf", encoding="utf-8")

            self.assertEqual(extract_pdf_text_pymupdf(path), "")

    def test_old_pdf_artifact_is_upgraded_with_extracted_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from app import main as main_module

            old_root = main_module.ROOT
            old_upload_index = main_module.UPLOAD_INDEX
            old_vector_index = main_module.VECTOR_INDEX
            try:
                main_module.ROOT = Path(temp_dir)
                main_module.UPLOAD_INDEX = Path(temp_dir) / "data" / "uploads.json"
                main_module.VECTOR_INDEX = Path(temp_dir) / "data" / "vectors.json"
                upload_path = Path(temp_dir) / "data" / "uploads" / "paper.pdf"
                upload_path.parent.mkdir(parents=True, exist_ok=True)
                upload_path.write_bytes(b"%PDF-1.4\nBT (Rotary position embeddings improve transformer attention.) Tj ET\n%%EOF")
                save_artifacts(
                    [
                        {
                            "id": "artifact-1",
                            "filename": "ROFORMER ENHANCED TRANSFORMER WITH ROTARY.pdf",
                            "content_type": "application/pdf",
                            "size": upload_path.stat().st_size,
                            "category": "pdf",
                            "path": "data/uploads/paper.pdf",
                            "preview": "",
                        }
                    ]
                )

                artifacts = load_artifacts()
            finally:
                main_module.ROOT = old_root
                main_module.UPLOAD_INDEX = old_upload_index
                main_module.VECTOR_INDEX = old_vector_index

        self.assertIn("Rotary position embeddings", artifacts[0]["cleaned_text"])
        self.assertGreater(artifacts[0]["metadata"]["chunk_count"], 0)

    def test_uploaded_files_context_uses_extracted_text(self) -> None:
        old_upload_index = os.environ.get("AIOS_UPLOAD_INDEX")
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["AIOS_UPLOAD_INDEX"] = os.path.join(temp_dir, "uploads.json")
            try:
                from app import main as main_module

                old_index = main_module.UPLOAD_INDEX
                main_module.UPLOAD_INDEX = main_module.Path(os.environ["AIOS_UPLOAD_INDEX"])
                main_module.save_artifacts(
                    [
                        {
                            "id": "artifact-1",
                            "filename": "notes.txt",
                            "category": "file",
                            "size": 12,
                            "extracted_text": "important extracted text",
                            "ocr_status": "not_required",
                        }
                    ]
                )

                context = uploaded_files_context_text(["artifact-1"])
            finally:
                main_module.UPLOAD_INDEX = old_index
                if old_upload_index is None:
                    os.environ.pop("AIOS_UPLOAD_INDEX", None)
                else:
                    os.environ["AIOS_UPLOAD_INDEX"] = old_upload_index

        self.assertIn("Extracted text", context)
        self.assertIn("important extracted text", context)

    def test_uploaded_image_without_ocr_still_has_context_note(self) -> None:
        old_upload_index = os.environ.get("AIOS_UPLOAD_INDEX")
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["AIOS_UPLOAD_INDEX"] = os.path.join(temp_dir, "uploads.json")
            try:
                from app import main as main_module

                old_index = main_module.UPLOAD_INDEX
                main_module.UPLOAD_INDEX = main_module.Path(os.environ["AIOS_UPLOAD_INDEX"])
                main_module.save_artifacts(
                    [
                        {
                            "id": "artifact-1",
                            "filename": "cross_dataset_alignmnet.png",
                            "category": "image",
                            "size": 36556,
                            "cleaned_text": "",
                            "ocr_status": "unavailable",
                            "ocr_error": "Install Tesseract or set AIOS_OCR_COMMAND to enable OCR.",
                            "metadata": {"chunk_count": 0},
                        }
                    ]
                )

                context = uploaded_files_context_text(["artifact-1"])
            finally:
                main_module.UPLOAD_INDEX = old_index
                if old_upload_index is None:
                    os.environ.pop("AIOS_UPLOAD_INDEX", None)
                else:
                    os.environ["AIOS_UPLOAD_INDEX"] = old_upload_index

        self.assertIn("cross_dataset_alignmnet.png", context)
        self.assertIn("No text was extracted", context)
        self.assertIn("OCR or vision support is required", context)


if __name__ == "__main__":
    unittest.main()
