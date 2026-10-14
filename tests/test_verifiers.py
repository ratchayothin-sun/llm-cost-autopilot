import pytest

from app.router import verifiers as v

ANSWER_NUM = "ลงท้ายคำตอบด้วยบรรทัดสุดท้ายในรูปแบบ ANSWER: <ตัวเลข> (เฉพาะตัวเลข)"
ANSWER_NAME = "ลงท้ายคำตอบด้วยบรรทัดสุดท้ายในรูปแบบ ANSWER: <คำตอบ> (ใส่เฉพาะชื่อวัน)"


def test_nonempty():
    assert v.nonempty([], "hi")
    assert not v.nonempty([], "   ")
    assert not v.nonempty([], "")


def test_empty_output_is_rejected():
    verdict = v.format_rules("anything", "  ")
    assert not verdict and verdict.reason == "empty"


def test_prompt_without_instructions_accepts_any_text():
    assert v.format_rules("What is the capital of Australia?", "Canberra")


def test_answer_line_required_when_prompt_demands_it():
    prompt = "1+1? " + ANSWER_NUM
    assert not v.format_rules(prompt, "The result is 2")
    assert v.format_rules(prompt, "1+1 is 2.\nANSWER: 2")


def test_answer_line_must_contain_a_number_when_a_number_is_requested():
    verdict = v.format_rules("1+1? " + ANSWER_NUM, "ANSWER: two")
    assert not verdict and verdict.reason == "ANSWER line has no number"
    # a name is fine when the prompt asks for a name
    assert v.format_rules("วันอะไร " + ANSWER_NAME, "ANSWER: วันจันทร์")


def test_answer_on_the_line_after_the_marker_counts():
    assert v.format_rules("1+1? " + ANSWER_NUM, "ANSWER:\n2")


def test_final_number_instruction():
    prompt = "17 * 24 = ? End your reply with the final number."
    assert v.format_rules(prompt, "17 * 24 = 408")
    assert not v.format_rules(prompt, "It is four hundred and eight")


def test_json_instruction():
    prompt = "Extract JSON with keys name, age from: 'Ann is 3'. Return only the JSON."
    assert v.format_rules(prompt, '{"name": "Ann", "age": 3}')
    assert v.format_rules(prompt, 'Here you go:\n```json\n{"name": "Ann", "age": 3}\n```')
    assert not v.format_rules(prompt, "{'name': 'Ann', 'age': 3}")     # python-style quotes
    assert not v.format_rules(prompt, "name: Ann, age: 3")


def test_find_json_handles_nesting_and_skips_broken_blocks():
    assert v.find_json('x {"a": {"b": 1}} y') == {"a": {"b": 1}}
    assert v.find_json('{broken} then {"ok": 1}') == {"ok": 1}
    assert v.find_json("no braces") is None


def test_unexpected_cjk_characters_are_rejected():
    assert not v.format_rules("ระยะทางเท่าไร", "ระยะทาง = ความเร็ว × 时间")
    assert v.format_rules("แปลเป็นภาษาจีน: สวัสดี", "你好")      # CJK was requested
    assert v.format_rules("翻訳してください", "こんにちは")      # CJK in the prompt itself


def test_prompt_text_joins_non_assistant_messages():
    messages = [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": [{"type": "text", "text": "Return JSON"}]},
        {"role": "assistant", "content": "ignored"},
    ]
    text = v.prompt_text(messages)
    assert "Be brief." in text and "Return JSON" in text and "ignored" not in text


def test_format_verify_uses_the_messages():
    messages = [{"role": "user", "content": "Return JSON please"}]
    assert not v.format_verify(messages, "no json here")
    assert v.format_verify(messages, '{"a": 1}')


@pytest.mark.parametrize("raw, expected", [
    ("Working...\nANSWER: 42", "42"),
    ("**ANSWER: จันทร์**", "จันทร์"),
    ("ANSWER: 1,250.", "1,250"),
    ("Canberra.", "Canberra"),
    ("first ANSWER: 1\nthen ANSWER: 2", "2"),             # the last marker wins
])
def test_extract_answer(raw, expected):
    assert v.extract_answer(raw) == expected


def test_last_number_ignores_thousands_commas():
    assert v.last_number("total 1,250 baht") == 1250
    assert v.last_number("no digits") is None


@pytest.mark.parametrize("a, b, expected", [
    ("ANSWER: 1,250", "The final answer is 1250", True),
    ("ANSWER: 12", "ANSWER: 21", False),
    ("Joe.", "joe", True),
    ("Ann", "Dan", False),
    ("Yes.", "Yes", True),
    ("x" * 300, "y" * 300, None),                          # long free text: undecidable
])
def test_answers_agree(a, b, expected):
    assert v.answers_agree(a, b) is expected
