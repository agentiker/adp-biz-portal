"""Markdown to plain text for channels that do not render markup."""

from __future__ import annotations

import pytest

from integrations.channels.text_format import BULLET, split_at_boundary, to_plain_text


def test_bold_and_italic_markers_are_removed_but_text_is_kept():
    assert to_plain_text("**已到港** 与 *预计* 时间") == "已到港 与 预计 时间"
    assert to_plain_text("___重点___") == "重点"


def test_headings_and_quotes_lose_their_markers():
    assert to_plain_text("## 查询结果\n> 备注内容") == "查询结果\n备注内容"


def test_bullets_become_readable_and_numbers_are_kept():
    result = to_plain_text("- 海运路线\n- 空运路线\n1. 订舱\n2. 报关")
    assert result == f"{BULLET} 海运路线\n{BULLET} 空运路线\n1. 订舱\n2. 报关"


def test_nested_bullet_indentation_survives():
    assert to_plain_text("- 顶层\n  - 次级") == f"{BULLET} 顶层\n  {BULLET} 次级"


def test_links_keep_both_label_and_url():
    """A customer may need to open the link, and bare URLs are tappable."""
    assert to_plain_text("[官网查询](https://adp.example.cn/portal)") == "官网查询 https://adp.example.cn/portal"


def test_images_degrade_to_their_alt_text():
    assert to_plain_text("![提单扫描件](https://x/y.png)") == "提单扫描件"
    assert to_plain_text("![](https://x/y.png)") == "图片"


def test_code_fences_and_inline_code_are_unwrapped():
    assert to_plain_text("```json\n{\"a\":1}\n```") == '{"a":1}'
    assert to_plain_text("字段 `ETA` 缺失") == "字段 ETA 缺失"


def test_tables_collapse_into_readable_rows():
    table = "| 提单号 | 状态 |\n| --- | --- |\n| BL-001 | 已到港 |"
    assert to_plain_text(table) == "提单号 | 状态\nBL-001 | 已到港"


def test_horizontal_rules_and_extra_blank_lines_are_trimmed():
    assert to_plain_text("上文\n\n---\n\n\n下文") == "上文\n\n下文"


def test_emoji_and_chinese_pass_through_untouched():
    assert to_plain_text("已到港 ✅ 请查收 🚢") == "已到港 ✅ 请查收 🚢"


def test_empty_input_is_empty_output():
    assert to_plain_text("") == ""
    assert to_plain_text("   \n  ") == ""
    assert to_plain_text(None) == ""


def test_buffer_below_the_minimum_is_held_back():
    chunk, rest = split_at_boundary("短句。", min_chars=40, max_chars=600)
    assert chunk == ""
    assert rest == "短句。"


def test_buffer_splits_at_the_last_sentence_end():
    buffer = "已收到您的查询请求，正在核对提单信息。船期已确认，预计明天离港"
    chunk, rest = split_at_boundary(buffer, min_chars=10, max_chars=600)
    assert chunk == "已收到您的查询请求，正在核对提单信息。"
    assert rest == "船期已确认，预计明天离港"


def test_buffer_without_a_boundary_waits_for_more_text():
    buffer = "这是一段没有任何句末标点的长文本用来验证不会被切断"
    chunk, rest = split_at_boundary(buffer, min_chars=10, max_chars=600)
    assert chunk == ""
    assert rest == buffer


def test_oversized_buffer_is_cut_even_without_a_boundary():
    """A run-on paragraph must not grow past what the channel accepts."""
    buffer = "无标点" * 100
    chunk, rest = split_at_boundary(buffer, min_chars=10, max_chars=50)
    assert len(chunk) == 50
    assert chunk + rest == buffer


def test_oversized_buffer_prefers_a_boundary_inside_the_limit():
    buffer = "第一句。" + "第二句没有结束" * 20
    chunk, rest = split_at_boundary(buffer, min_chars=10, max_chars=30)
    assert chunk == "第一句。"
    assert chunk + rest == buffer


def test_newline_counts_as_a_boundary():
    chunk, rest = split_at_boundary("第一行\n第二行继续", min_chars=3, max_chars=600)
    assert chunk == "第一行\n"
    assert rest == "第二行继续"
