"""SentenceChunker: where a streamed reply is cut into sentences for TTS."""

import pytest

from app.voice.sentences import SentenceChunker


def chunk_all(text: str, *, size: int | None = None, max_chars: int = 300) -> list[str]:
    """Feed `text` whole (size=None) or in pieces of `size` characters, then flush."""
    chunker = SentenceChunker(max_chars)
    out: list[str] = []
    if size is None:
        out += chunker.feed(text)
    else:
        for i in range(0, len(text), size):
            out += chunker.feed(text[i:i + size])
    return out + chunker.flush()


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Hello there. How are you? I am fine!", ["Hello there.", "How are you?", "I am fine!"]),
        ("नमस्ते! मैं आपकी मदद कर सकता हूँ। आप क्या जानना चाहते हैं?", ["नमस्ते!", "मैं आपकी मदद कर सकता हूँ।", "आप क्या जानना चाहते हैं?"]),
        ("Namaste! Main aapki appointment book karne mein help kar sakta hoon.",
         ["Namaste!", "Main aapki appointment book karne mein help kar sakta hoon."]),
        ("मुझे कल का appointment confirm करना है। Please wait.", ["मुझे कल का appointment confirm करना है।", "Please wait."]),
        ("No final punctuation", ["No final punctuation"]),
        ("The price is 3.5 rupees. Next one.", ["The price is 3.5 rupees.", "Next one."]),
        ("Ask Dr. Sharma about it. Thanks.", ["Ask Dr. Sharma about it.", "Thanks."]),
        ("Use e.g. a pen. Done.", ["Use e.g. a pen.", "Done."]),
        ("Meet A. Kumar today. Bye.", ["Meet A. Kumar today.", "Bye."]),
        ('He said "go." Then left.', ['He said "go."', "Then left."]),
        ("Line one\nLine two", ["Line one", "Line two"]),
        ("Wait... what? Really?!", ["Wait...", "what?", "Really?!"]),
        ("   ", []),
        ("", []),
    ],
)
def test_sentences_are_cut_at_the_right_places(text, expected):
    assert chunk_all(text) == expected


@pytest.mark.parametrize("size", [1, 2, 3, 5, 7])
def test_the_result_does_not_depend_on_how_the_text_was_streamed(size):
    text = "Namaste! Price is 3.5 rupees. Ask Dr. Rao. मैं मदद कर सकता हूँ। Kya aap ready hain? Done"
    assert chunk_all(text, size=size) == chunk_all(text)


def test_a_sentence_is_emitted_as_soon_as_it_is_complete_not_at_the_end():
    chunker = SentenceChunker()
    assert chunker.feed("Pehla vaakya") == []
    assert chunker.feed(" khatam. ") == ["Pehla vaakya khatam."]  # the following space proves the dot is a full stop
    assert chunker.feed("Doosra shuru") == []
    assert chunker.feed(" hota hai?") == ["Doosra shuru hota hai?"]  # '?' is complete immediately
    assert chunker.flush() == []


def test_a_dot_at_the_end_of_the_buffer_waits_for_the_next_character():
    chunker = SentenceChunker()
    assert chunker.feed("It costs 3.") == []  # could still become "3.5"
    assert chunker.feed("5 rupees") == []
    assert chunker.flush() == ["It costs 3.5 rupees"]


def test_text_is_never_rewritten_only_split_and_trimmed():
    text = "  Aap कैसे हैं?  Main theek hoon.\n  Shukriya!  "
    pieces = chunk_all(text)
    assert pieces == ["Aap कैसे हैं?", "Main theek hoon.", "Shukriya!"]
    assert "".join("".join(pieces).split()) == "".join(text.split())  # same characters, in the same order


def test_pieces_without_any_letter_or_digit_are_dropped():
    assert chunk_all("Okay?! ... ! Fine.") == ["Okay?!", "Fine."]


def test_a_long_sentence_is_split_at_a_clause_or_space_within_max_chars():
    text = "word " * 40 + "end."  # 204 characters, no boundary until the end
    pieces = chunk_all(text, max_chars=50)
    assert all(len(p) <= 50 for p in pieces) and len(pieces) > 1
    assert " ".join(pieces).split() == text.split()  # nothing lost or reordered

    clause = "Pehli baat yeh hai, doosri baat woh hai, aur teesri baat kuch aur hi hai " * 2
    assert all(len(p) <= 60 for p in chunk_all(clause, max_chars=60))


def test_a_long_streamed_sentence_is_split_before_its_terminator_arrives():
    chunker = SentenceChunker(max_chars=40)
    out = chunker.feed("one two three four five six seven eight nine ten eleven twelve")
    assert out and all(len(p) <= 40 for p in out)  # first audio need not wait for the full stop


def test_text_without_spaces_is_hard_cut():
    pieces = chunk_all("a" * 130, max_chars=50)
    assert [len(p) for p in pieces] == [50, 50, 30]


def test_max_chars_has_a_sane_minimum():
    with pytest.raises(ValueError):
        SentenceChunker(5)
