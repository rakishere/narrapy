# tests/test_text_cleanup.py - part of narrapy (https://github.com/rakishere/narrapy)
# Author: Rakesh Sharma
# Copyright (c) 2026 Rakesh Sharma
# Licensed under the MIT License. See the LICENSE file for details.
# SPDX-License-Identifier: MIT

"""Tests for PDF text cleanup: running footers and doubled lines must not be
read aloud, and ordinary text must be kept. The PDFs are built on the fly."""

import pymupdf
import pytest

from narrapy.cli import (drop_doubled_lines, extract_pages, find_repeated_edges,
                         normalize_for_compare)

FOOTER = "LITTLE BLACK BOOK FOR STUNNING SUCCESS"


def padded_footer(page_number):
    # Like the real book: padding changes with the page number and the
    # whole block is longer than 120 characters.
    gap = " " * (40 - len(str(page_number)))
    return f"{FOOTER}{gap}{page_number}{' ' * 80}(c) ROBIN SHARMA"


def make_pdf(pages):
    """pages: list of (body_text, footer_text or None). Returns an open document."""
    doc = pymupdf.open()
    for body, footer in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(72, 72, 540, 700), body, fontsize=11)
        if footer:
            page.insert_text((20, 800), footer, fontsize=5)
    return doc


def all_text(doc):
    pages = extract_pages(doc, 0, len(doc) - 1)
    return "\n".join(p for i in sorted(pages) for p in pages[i])


# --- normalize_for_compare --------------------------------------------------

def test_normalize_ignores_page_numbers_and_padding():
    assert normalize_for_compare(padded_footer(7)) == normalize_for_compare(padded_footer(123))


def test_normalized_footer_is_short_enough_to_count():
    assert len(padded_footer(11)) > 120
    assert len(normalize_for_compare(padded_footer(11))) < 120


# --- drop_doubled_lines -----------------------------------------------------

def test_exact_doubled_line_is_read_once():
    assert drop_doubled_lines("THIS DAY IS SPECIAL\nTHIS DAY IS SPECIAL") == "THIS DAY IS SPECIAL"


def test_doubled_line_with_trailing_space_is_read_once():
    text = "The best way to create results\nThe best way to create results \nin your life."
    assert drop_doubled_lines(text) == "The best way to create results\nin your life."


def test_copy_glued_to_next_line_is_removed():
    text = ("1) Pay Attention To Life:\n"
            "1) Pay Attention To Life: It's really easy to fall\n"
            "It's really easy to fall \n"
            "asleep to life.")
    assert drop_doubled_lines(text) == (
        "1) Pay Attention To Life:\nIt's really easy to fall \nasleep to life.")


def test_short_glued_copy_is_removed():
    text = "Yet, \nYet, deep within us we know\ndeep within us we know \nit is time."
    assert drop_doubled_lines(text) == "Yet, \ndeep within us we know \nit is time."


@pytest.mark.parametrize("text", [
    "Never give up\nNever give up on yourself.",        # line starts with the one before
    "Work hard.\nPlay hard.\nWork hard.",                # repeat, but not back to back
    "one\n\n\ntwo",                                      # blank lines are left alone
    "A single line of text.",
])
def test_ordinary_text_is_kept(text):
    assert drop_doubled_lines(text) == text


# --- whole-PDF extraction ---------------------------------------------------

BODIES = ["Leadership is a philosophy.", "Practice every single day.",
          "Time is precious and short.", "Start before you feel ready.",
          "Small wins build momentum.", "Nothing happens until you move."]


def test_padded_running_footer_is_skipped():
    doc = make_pdf([(body, padded_footer(n)) for n, body in enumerate(BODIES, 1)])
    assert normalize_for_compare(padded_footer(1)) in find_repeated_edges(doc, 0, len(doc) - 1)
    text = all_text(doc)
    assert FOOTER not in text.upper()
    for body in BODIES:
        assert body in text


def test_doubled_heading_in_pdf_is_read_once():
    doc = make_pdf([("THIS DAY IS SPECIAL\nTHIS DAY IS SPECIAL\nToday is unique.", None)])
    assert all_text(doc).count("THIS DAY IS SPECIAL") == 1


def test_body_text_repeated_on_few_pages_is_kept():
    # A sentence on 2 of 10 pages is content, not a running header.
    pages = [(f"Chapter text {n}.", None) for n in range(10)]
    pages[2] = ("Nothing happens until you move.", None)
    pages[7] = ("Nothing happens until you move.", None)
    text = all_text(make_pdf(pages))
    assert text.count("Nothing happens until you move.") == 2
