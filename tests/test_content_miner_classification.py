"""Tests for content_miner classification: questions, approvals, corrections, code blocks."""

from __future__ import annotations

import re

from claudealytics.analytics.parsers.content_miner import (
    _APPROVAL_RE,
    _CORRECTION_RE,
    _FENCED_CODE_RE,
    _INLINE_CODE_RE,
)

# ── Question Detection ────────────────────────────────────────────


def _has_question(text: str) -> bool:
    """Reproduce the question detection logic from content_miner."""
    text_no_code = _FENCED_CODE_RE.sub("", text)
    return bool(re.search(r"\?\s|\?$", text_no_code))


class TestQuestionDetection:
    def test_simple_question(self):
        assert _has_question("What is this?")

    def test_question_mid_text(self):
        assert _has_question("Can you fix this? Also update the tests.")

    def test_question_after_paragraph(self):
        assert _has_question("I updated the file.\nCan you review it?")

    def test_question_inside_code_block_ignored(self):
        assert not _has_question("```\nwhat is this?\n```")

    def test_question_outside_code_block_detected(self):
        assert _has_question("Can you fix this?\n```\nsome code\n```")

    def test_no_question_mark(self):
        assert not _has_question("Please fix the bug.")

    def test_multiline_message_with_question(self):
        msg = "I noticed something weird.\n\nIs this expected behavior?\n\nAlso here's the log output."
        assert _has_question(msg)

    def test_message_ending_with_code_block_but_has_question(self):
        msg = "Can you fix this?\n```python\nprint('hello')\n```"
        assert _has_question(msg)


# ── Code Block Detection ──────────────────────────────────────────


def _has_code(text: str) -> bool:
    """Reproduce the code detection logic from content_miner."""
    return "```" in text or bool(_INLINE_CODE_RE.search(text))


class TestCodeBlockDetection:
    def test_triple_backtick(self):
        assert _has_code("Here is code:\n```python\nprint('hi')\n```")

    def test_proper_inline_code(self):
        assert _has_code("Use the `foo` function.")

    def test_single_backtick_no_match(self):
        # A lone backtick (not wrapping content) should NOT count
        assert not _has_code("I don`t know")

    def test_no_code(self):
        assert not _has_code("Please fix the login page.")

    def test_inline_code_multiword(self):
        assert _has_code("Run `npm install` to fix it.")


# ── Approval Regex ────────────────────────────────────────────────


class TestApprovalRegex:
    # True positives
    def test_lgtm(self):
        assert _APPROVAL_RE.search("lgtm")

    def test_looks_good(self):
        assert _APPROVAL_RE.search("looks good")

    def test_go_ahead(self):
        assert _APPROVAL_RE.search("go ahead")

    def test_proceed(self):
        assert _APPROVAL_RE.search("proceed")

    def test_approved(self):
        assert _APPROVAL_RE.search("approved")

    def test_perfect(self):
        assert _APPROVAL_RE.search("perfect")

    def test_ship_it(self):
        assert _APPROVAL_RE.search("ship it")

    def test_sounds_good(self):
        assert _APPROVAL_RE.search("sounds good")

    def test_that_works(self):
        assert _APPROVAL_RE.search("that works")

    def test_yes_standalone(self):
        assert _APPROVAL_RE.search("yes")

    def test_yes_comma(self):
        assert _APPROVAL_RE.search("yes, do it")

    def test_great_thanks(self):
        assert _APPROVAL_RE.search("great, thanks")

    def test_sure_thing(self):
        assert _APPROVAL_RE.search("sure thing")

    # False positives to reject
    def test_make_sure_rejected(self):
        assert not _APPROVAL_RE.search("make sure to test it")

    def test_token_rejected(self):
        assert not _APPROVAL_RE.search("update the token")

    def test_bookmark_rejected(self):
        assert not _APPROVAL_RE.search("add a bookmark")

    def test_greater_rejected(self):
        assert not _APPROVAL_RE.search("use a greater value")

    def test_yesterday_rejected(self):
        assert not _APPROVAL_RE.search("I did this yesterday")

    def test_not_sure_rejected(self):
        assert not _APPROVAL_RE.search("I'm not sure about this")


# ── Correction Regex ──────────────────────────────────────────────


class TestCorrectionRegex:
    # True positives
    def test_no_comma(self):
        assert _CORRECTION_RE.search("no, that's wrong")

    def test_thats_not(self):
        assert _CORRECTION_RE.search("that's not what I meant")

    def test_not_what_i(self):
        assert _CORRECTION_RE.search("not what I asked for")

    def test_wrong(self):
        assert _CORRECTION_RE.search("that's wrong")

    def test_revert(self):
        assert _CORRECTION_RE.search("please revert that change")

    def test_undo(self):
        assert _CORRECTION_RE.search("undo the last edit")

    def test_roll_back(self):
        assert _CORRECTION_RE.search("roll back to the previous version")

    def test_that_broke(self):
        assert _CORRECTION_RE.search("that broke the tests")

    def test_stop_exclaim(self):
        assert _CORRECTION_RE.search("stop!")

    def test_stop_doing(self):
        assert _CORRECTION_RE.search("stop doing that")

    # False positives to reject
    def test_actually_filler_rejected(self):
        assert not _CORRECTION_RE.search("actually, let's also add logging")

    def test_dont_forget_rejected(self):
        assert not _CORRECTION_RE.search("don't forget to test")

    def test_use_instead_rejected(self):
        assert not _CORRECTION_RE.search("use X instead of Y")

    def test_stop_in_word_rejected(self):
        assert not _CORRECTION_RE.search("the stopwatch is broken")

    def test_wrong_with_rejected(self):
        assert not _CORRECTION_RE.search("what's wrong with the API?")


# ── Classification Priority ──────────────────────────────────────


class TestClassificationPriority:
    def _classify(self, text: str) -> str:
        """Reproduce the classification logic from content_miner."""
        text_length = len(text)
        if _CORRECTION_RE.search(text):
            return "correction"
        if text_length < 80 and _APPROVAL_RE.search(text):
            return "approval"
        return "new_instruction"

    def test_short_correction_not_approval(self):
        # "no, wrong" is short and could match approval "ok" — correction wins
        assert self._classify("no, that's wrong") == "correction"

    def test_short_approval(self):
        assert self._classify("looks good") == "approval"

    def test_long_message_not_approval(self):
        msg = "yes I agree with the approach, let me explain what we should do next with the authentication flow"
        assert self._classify(msg) == "new_instruction"

    def test_stop_period_is_correction(self):
        assert self._classify("stop.") == "correction"
