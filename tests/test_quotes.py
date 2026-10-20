"""Quote extraction and MCP payload isolation. Run: python -m unittest discover -s tests -p test_quotes.py"""
import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import calibre_mcp as m


class LibraryStub:
    name = "fixture"
    text = 'A source passage.\n<script>alert("book text")</script>\nFinal words.'

    def describe(self, ids):
        return [{"id": 1, "title": "<b>Book</b>", "authors": ["Author"]}] if ids == [1] else []

    def text_for(self, book_id, fmt):
        return self.text, fmt or "EPUB", "fixture"


class QuoteTests(unittest.TestCase):
    def setUp(self):
        self.lib = LibraryStub()
        self.patch = patch.object(m, "LIB", self.lib)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        for name, value in (("LIBS", {"fixture": self.lib}), ("_DEFAULT_LIB", ["fixture"])):
            p = patch.object(m, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.chapters_patch = patch.object(m, "book_chapters", side_effect=lambda book_id, fmt: (
            m.structure.chapter_map(self.lib.text, m.fold), self.lib.text, fmt, "fixture"))
        self.chapters_patch.start()
        self.addCleanup(self.chapters_patch.stop)

    def result(self, **kwargs):
        return m.calibre_show_quotes([m.QuoteRef(book_id=1, **kwargs)])

    def test_verbatim_and_attribution(self):
        payload = self.result(offset=18, max_chars=6000, format="EPUB").model_dump(by_alias=True)
        item = payload["_meta"]["calibreQuotes"]["passages"][0]
        self.assertEqual(item["text"], self.lib.text[18:])
        self.assertEqual(item["label"], "<b>Book</b>")
        self.assertEqual(item["authors"], ["Author"])
        self.assertEqual(item["end_offset"], len(self.lib.text))
        self.assertEqual(item["format"], "EPUB")
        self.assertIn("percent", item["location"])
        self.assertEqual(item["library"], "fixture")

    def test_text_only_in_view_metadata(self):
        payload = self.result().model_dump(by_alias=True)
        view = payload.pop("_meta")
        self.assertEqual(view["calibreQuotes"]["passages"][0]["text"], self.lib.text)
        model_payload = json.dumps(payload)
        self.assertNotIn(self.lib.text, model_payload)
        self.assertNotIn("script", model_payload)
        self.assertEqual(payload["structuredContent"]["references"][0]["offset"], 0)

    def test_exact_range_keeps_final_word(self):
        expected = self.lib.text[:17]
        item = self.result(offset=0, max_chars=17).meta["calibreQuotes"]["passages"][0]
        self.assertEqual(item["text"], "A source passage.")
        self.assertEqual(item["text"], expected)

    def test_exact_character_window(self):
        expected = self.lib.text[2:22]
        item = self.result(offset=2, max_chars=20).meta["calibreQuotes"]["passages"][0]
        self.assertEqual(item["text"], expected)

    def test_missing_book_and_invalid_offset(self):
        with self.assertRaises(m.ToolError):
            m.calibre_show_quotes([m.QuoteRef(book_id=999)])
        with self.assertRaises(m.ToolError):
            self.result(offset=999)

    def test_reference_validation(self):
        for kwargs in ({"book_id": 0}, {"book_id": 1, "offset": -1},
                       {"book_id": 1, "max_chars": 6001}, {"book_id": 1, "text": "copied quote"}):
            with self.assertRaises(ValueError):
                m.QuoteRef(**kwargs)

    def test_global_limit_and_end_of_text(self):
        with patch.object(m, "MAX_CHARS", 8):
            item = self.result(max_chars=20).meta["calibreQuotes"]["passages"][0]
        self.assertEqual(item["text"], self.lib.text[:8])
        self.assertEqual(item["end_offset"], 8)
        item = self.result(offset=len(self.lib.text) - 1).meta["calibreQuotes"]["passages"][0]
        self.assertEqual(item["text"], ".")
        self.assertEqual(item["end_offset"], len(self.lib.text))

    def test_mcp_schema_and_result_metadata(self):
        async def call():
            tools = await m.mcp.list_tools()
            tool = next(t for t in tools if t.name == "calibre_show_quotes")
            schema = tool.model_dump(by_alias=True)
            self.assertEqual(schema["_meta"]["ui"]["resourceUri"], m.GALLERY_URI)
            self.assertIn("library", schema["inputSchema"]["properties"])
            self.assertEqual(schema["inputSchema"]["properties"]["passages"]["maxItems"], 12)
            result = await m.mcp.call_tool("calibre_show_quotes", {"passages": [{"book_id": 1}]})
            # Direct-call return conventions differ between MCP SDK versions.
            if isinstance(result, m.CallToolResult):
                payload = result.model_dump(by_alias=True)
                self.assertEqual(payload.pop("_meta")["calibreQuotes"]["passages"][0]["text"], self.lib.text)
                self.assertNotIn("script", json.dumps(payload))
            else:
                self.assertNotIn("script", str(result))
            for passages in ([], [{"book_id": 1}] * 13, [{"book_id": 1, "text": "not accepted"}]):
                with self.assertRaises(m.ToolError):
                    await m.mcp.call_tool("calibre_show_quotes", {"passages": passages})
        asyncio.run(call())

    def test_selected_library_is_used_for_text(self):
        primary, secondary = LibraryStub(), LibraryStub()
        primary.name, secondary.name = "primary", "secondary"
        secondary.text = "A different library's passage."
        with patch.object(m, "LIB", m._LibProxy()), \
             patch.object(m, "LIBS", {"primary": primary, "secondary": secondary}), \
             patch.object(m, "_DEFAULT_LIB", ["primary"]):
            result = m.calibre_show_quotes([m.QuoteRef(book_id=1)], library="secondary")
        self.assertEqual(result.meta["calibreQuotes"]["passages"][0]["text"], secondary.text)

    def test_reader_text_only_in_view_metadata(self):
        r = m.calibre_read_view(book_id=1).model_dump(by_alias=True)
        view = r.pop("_meta")["calibreReader"]
        self.assertEqual(view["text"], self.lib.text)
        self.assertEqual(view["library"], "fixture")
        self.assertIn("chapters", view)
        self.assertNotIn(self.lib.text, json.dumps(r))
        self.assertNotIn("script", json.dumps(r))

    def test_reader_pagination_and_format(self):
        self.lib.text = "First chapter\n" + "word " * 1500
        first = m.calibre_read_view(book_id=1, max_chars=500, format="EPUB").meta["calibreReader"]
        second = m.calibre_read_view(book_id=1, offset=first["next_offset"], max_chars=500,
                                    format=first["format"]).meta["calibreReader"]
        self.assertEqual(first["offset"], 0)
        self.assertEqual(second["offset"], first["next_offset"])
        self.assertEqual(first["text"] + second["text"], self.lib.text[:second["next_offset"]])

    def test_reader_app_only_schema(self):
        async def schema():
            tools = await m.mcp.list_tools()
            t = next(t for t in tools if t.name == "calibre_read_view")
            self.assertEqual(t.model_dump(by_alias=True)["_meta"]["ui"]["visibility"], ["app"])
        asyncio.run(schema())

    def test_reader_preserves_selected_library(self):
        primary, secondary = LibraryStub(), LibraryStub()
        primary.name, secondary.name = "primary", "secondary"
        secondary.text = "Only the secondary library contains this passage."
        with patch.object(m, "LIB", m._LibProxy()), \
             patch.object(m, "LIBS", {"primary": primary, "secondary": secondary}), \
             patch.object(m, "_DEFAULT_LIB", ["primary"]):
            view = m.calibre_read_view(book_id=1, library="secondary").meta["calibreReader"]
        self.assertEqual(view["text"], secondary.text)
        self.assertEqual(view["library"], "secondary")

    def test_quote_chapter_reference(self):
        self.lib.text = "Chapter 1: Starting\n" + "first paragraph " * 50
        cmap = {"chapters": [{"title": "Chapter 1: Starting", "index": 0, "offset": 0,
                              "end": len(self.lib.text), "chars": len(self.lib.text)}]}
        with patch.object(m, "book_chapters", return_value=(cmap, self.lib.text, "EPUB", "fixture")):
            item = self.result(offset=30).meta["calibreQuotes"]["passages"][0]
        self.assertEqual(item["location"]["chapter"], "Chapter 1: Starting")


if __name__ == "__main__":
    unittest.main()
