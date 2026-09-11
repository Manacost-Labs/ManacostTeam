#!/usr/bin/env python3
"""Focused tests for editor-ready Markdown validation."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATE = ROOT / "scripts/validate_editor_output.py"
sys.path.insert(0, str(ROOT / "scripts"))

from validate_editor_output import visible_external_links  # noqa: E402


VALID_OPENING = """# Рабочий заголовок

*Актуально на 1 сентября 2026 года.*

## Коротко

Главный вывод подтверждён [проверенным источником](https://example.com/source). Существенные границы вывода названы рядом.
"""


class EditorOutputValidationTest(unittest.TestCase):
    def run_validator(self, markdown: str) -> tuple[subprocess.CompletedProcess[str], str]:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "editor-ready.md"
            path.write_text(markdown, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VALIDATE), str(path)],
                check=False,
                capture_output=True,
                text=True,
            )
            preserved = path.read_text(encoding="utf-8")
        return result, preserved

    def test_valid_editor_markdown_preserves_links(self) -> None:
        markdown = (
            VALID_OPENING
            + """
## Контекст

Вывод относится только к описанной аудитории и периоду.

## Основной материал

Подробности подтверждает [проверенный первоисточник](https://example.com/archive_(v2_(final))/source?section=(one_(two))).

## Что важно не исказить

- Наблюдение нельзя превращать в универсальное правило.
"""
        )
        result, preserved = self.run_validator(markdown)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Editor output: PASS", result.stdout)
        self.assertNotIn("[internal-id]", result.stdout)
        self.assertEqual(preserved, markdown)

    def test_unfilled_shipped_template_is_rejected(self) -> None:
        template = (
            ROOT / "references/templates/editor-ready.md"
        ).read_text(encoding="utf-8")
        result, _ = self.run_validator(template)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[unfinished-placeholder]", result.stdout)

    def test_reference_and_autolinks_count_as_visible_sources(self) -> None:
        for source_markup in (
            "<https://example.com/source>",
            "https://example.com/source",
            "https://en.wikipedia.org/wiki/Foo_(bar)",
            "https://example.com/a(b)c",
            '[проверенным источником](https://example.com/source "Название")',
            "<code>[проверенным источником](https://example.com/source)</code>",
            r"\![проверенным источником](https://example.com/source)",
            r"\`[проверенным источником](https://example.com/source)\`",
            r"\``[проверенным источником](https://example.com/source)\``",
        ):
            with self.subTest(source_markup=source_markup):
                markdown = f"""# Заголовок

*Актуально на 1 сентября 2026 года.*

## Коротко

Главный вывод подтверждён {source_markup}. Границы вывода названы рядом.

## Что важно не исказить

- Вывод относится только к указанному срезу.
"""
                result, _ = self.run_validator(markdown)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("[missing-source-link]", result.stdout)

        for definition in (
            "[src]: https://example.com/source",
            "[src]: <https://example.com/source> 'Название'",
        ):
            for reference_markup in (
                "[проверенным источником][src]",
                r"\![проверенным источником][src]",
            ):
                with self.subTest(
                    definition=definition,
                    reference_markup=reference_markup,
                ):
                    markdown = f"""# Заголовок

*Актуально на 1 сентября 2026 года.*

## Коротко

Главный вывод подтверждён {reference_markup}. Границы вывода названы рядом.

## Что важно не исказить

- Вывод относится к указанному периоду.

{definition}
"""
                    result, _ = self.run_validator(markdown)
                    self.assertEqual(
                        result.returncode,
                        0,
                        result.stdout + result.stderr,
                    )
                    self.assertNotIn("[missing-source-link]", result.stdout)

        markdown = """# Заголовок

*Актуально на 1 сентября 2026 года.*

## Коротко

Главный вывод подтверждён [Источником]. Границы вывода названы рядом.

[Источником]: https://example.com/source
"""
        result, _ = self.run_validator(markdown)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("[missing-source-link]", result.stdout)

    def test_list_continuation_links_count_as_visible_sources(self) -> None:
        for list_block in (
            "- Наблюдение\n    подтверждает [источник](https://example.com/source).",
            "- Наблюдение\n\n    [Источник](https://example.com/source) подтверждает его.",
        ):
            with self.subTest(list_block=list_block):
                markdown = f"""# Заголовок

*Актуально на 1 сентября 2026 года.*

## Коротко

{list_block}

Границы вывода названы рядом.
"""
                result, _ = self.run_validator(markdown)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("[missing-source-link]", result.stdout)

    def test_invalid_unquoted_link_title_is_not_treated_as_a_source(self) -> None:
        markdown = """# Заголовок

*Актуально на 1 сентября 2026 года.*

## Коротко

Главный вывод якобы подтверждён [источником](https://example.com/source junk). Границы вывода названы рядом.
"""
        result, _ = self.run_validator(markdown)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[missing-source-link]", result.stdout)

    def test_invalid_reference_definition_title_is_not_a_source(self) -> None:
        for definition in (
            "[src]: https://example.com/source junk",
            "[src]: <https://example.com/source> junk",
        ):
            with self.subTest(definition=definition):
                markdown = f"""# Заголовок

*Актуально на 1 сентября 2026 года.*

## Коротко

Главный вывод якобы подтверждён [источником][src]. Границы вывода названы рядом.

{definition}
"""
                result, _ = self.run_validator(markdown)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("[missing-source-link]", result.stdout)

    def test_hidden_link_like_text_does_not_count_as_a_source(self) -> None:
        for source_markup in (
            '\n\n[local]: /local "[источник](https://example.com/source)"',
            "\n\n[^1]: [источник](https://example.com/source)",
            '<span title="[источник](https://example.com/source)">текст</span>',
            '<span title="a > [источник](https://example.com/source)">текст</span>',
            "<span title='a > [источник](https://example.com/source)'>текст</span>",
            '<code data-x="[источник](https://example.com/source)">текст</code>',
            '[локальная ссылка](/local "[источник](https://example.com/source)")',
        ):
            with self.subTest(source_markup=source_markup):
                markdown = f"""# Заголовок

*Актуально на 1 сентября 2026 года.*

## Коротко

Здесь нет внешней ссылки: {source_markup}
"""
                result, _ = self.run_validator(markdown)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("[missing-source-link]", result.stdout)

    def test_links_inside_explicitly_hidden_html_do_not_count_as_sources(self) -> None:
        for source_markup in (
            '<span hidden>[источник](https://example.com/source)</span>',
            '<span aria-hidden="true">[источник](https://example.com/source)</span>',
            '<span style="display: none">[источник](https://example.com/source)</span>',
            '<span style="visibility: hidden">[источник](https://example.com/source)</span>',
        ):
            with self.subTest(source_markup=source_markup):
                markdown = f"""# Заголовок

*Актуально на 1 сентября 2026 года.*

## Коротко

Здесь нет видимой внешней ссылки: {source_markup}
"""
                result, _ = self.run_validator(markdown)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("[missing-source-link]", result.stdout)

    def test_malformed_external_urls_do_not_count_as_sources(self) -> None:
        for source_markup in (
            "[источник](https://)",
            "[источник](https://?x)",
            "[источник](http://.)",
            "<http://?>",
            "[](https://example.com/source)",
            "[   ](https://example.com/source)",
            "foohttps://example.com/source",
        ):
            with self.subTest(source_markup=source_markup):
                markdown = f"""# Заголовок

*Актуально на 1 сентября 2026 года.*

## Коротко

Некорректный адрес не является источником: {source_markup}
"""
                result, _ = self.run_validator(markdown)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("[missing-source-link]", result.stdout)

    def test_balanced_bare_url_identity_is_preserved(self) -> None:
        markdown = (
            "https://en.wikipedia.org/wiki/Foo_(bar) "
            "https://example.com/a(b)c"
        )
        self.assertEqual(
            visible_external_links(markdown),
            [
                "https://en.wikipedia.org/wiki/Foo_(bar)",
                "https://example.com/a(b)c",
            ],
        )

    def test_emphasis_delimiters_are_not_part_of_bare_url_identity(self) -> None:
        for markup in (
            "**https://example.com/source**",
            "*https://example.com/source*",
            "~~https://example.com/source~~",
            "_https://example.com/source_",
        ):
            with self.subTest(markup=markup):
                self.assertEqual(
                    visible_external_links(markup),
                    ["https://example.com/source"],
                )

    def test_code_and_escaped_markup_do_not_count_as_visible_sources(self) -> None:
        for source_markup in (
            "`[источник](https://example.com/source)`",
            "``[источник](https://example.com/source)``",
            r"\\`[источник](https://example.com/source)\\`",
            r"\\``[источник](https://example.com/source)\\``",
            r"\[источник](https://example.com/source)",
            r"\<https://example.com/source>",
            r"\\![источник](https://example.com/source)",
            "\n\n    [источник](https://example.com/source)",
            "\n\n\t[источник](https://example.com/source)",
            "\n\n- ```\n  [источник](https://example.com/source)\n  ```",
            "\n\n1. ```\n   [источник](https://example.com/source)\n   ```",
            "\n\n<pre>\n[источник](https://example.com/source)\n</pre>",
            "\n\n<script>\n[источник](https://example.com/source)\n</script>",
            "\n\n<div>\n[источник](https://example.com/source)\n</div>",
            "\n\n<details>\n[источник](https://example.com/source)\n</details>",
            "\n\n<div>\nтекст\n</div>\n[источник](https://example.com/source)",
            "\n\n<span>\n[источник](https://example.com/source)\n</span>",
            "\n\n<x-box>\n[источник](https://example.com/source)\n</x-box>",
            "\n\n<?x\n[источник](https://example.com/source)\n?>",
            "\n\n<![CDATA[\n[источник](https://example.com/source)\n]]>",
            "\n\n<!DOCTYPE\n[источник](https://example.com/source)\n>",
            "\n\n>     [источник](https://example.com/source)",
        ):
            with self.subTest(source_markup=source_markup):
                markdown = f"""# Заголовок

*Актуально на 1 сентября 2026 года.*

## Коротко

Это только пример записи, а не ссылка: {source_markup}
"""
                result, _ = self.run_validator(markdown)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("[missing-source-link]", result.stdout)

    def test_container_exit_restores_visible_source_parsing(self) -> None:
        for hidden_block in (
            "- ```html\n  <!-- незакрытый пример",
            "- <div>\n  скрытый пример",
            "- <!-- скрытый пример",
            "> ```html\n> скрытый пример",
        ):
            with self.subTest(hidden_block=hidden_block):
                markdown = f"""# Заголовок

*Актуально на 1 сентября 2026 года.*

## Коротко

{hidden_block}
[Источник](https://example.com/source) подтверждает вывод. Его границы названы рядом.
"""
                result, _ = self.run_validator(markdown)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("[missing-source-link]", result.stdout)

    def test_list_scoped_raw_html_keeps_inner_link_hidden(self) -> None:
        markdown = """# Заголовок

*Актуально на 1 сентября 2026 года.*

## Коротко

- Наблюдение

    <div>
    [источник](https://example.com/source)
    </div>
"""
        result, _ = self.run_validator(markdown)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[missing-source-link]", result.stdout)

    def test_comment_tokens_inside_code_do_not_hide_a_real_source(self) -> None:
        for example in (
            "```html\n<!-- только пример\n```",
            "`<!-- только пример -->`",
            r"\<!-- [это видимый текст](https://example.com/inside) -->",
        ):
            with self.subTest(example=example):
                markdown = f"""# Заголовок

*Актуально на 1 сентября 2026 года.*

## Коротко

{example}

[Источник](https://example.com/source) подтверждает вывод. Его границы названы рядом.
"""
                result, _ = self.run_validator(markdown)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("[missing-source-link]", result.stdout)

    def test_indented_lazy_paragraph_continuation_is_visible(self) -> None:
        markdown = """# Заголовок

*Актуально на 1 сентября 2026 года.*

## Коротко

Вывод подтверждён ниже.
    [Источник](https://example.com/source) задаёт его границы.
"""
        result, _ = self.run_validator(markdown)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("[missing-source-link]", result.stdout)

    def test_escaped_reference_link_does_not_count_as_visible_source(self) -> None:
        markdown = r"""# Заголовок

*Актуально на 1 сентября 2026 года.*

## Коротко

Это только пример записи, а не ссылка: \[источник][src].

[src]: https://example.com/source
"""
        result, _ = self.run_validator(markdown)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[missing-source-link]", result.stdout)

    def test_reference_image_does_not_count_as_a_source_link(self) -> None:
        markdown = """# Заголовок

*Актуально на 1 сентября 2026 года.*

## Коротко

Главный вывод дан рядом с изображением ![график][img]. Границы вывода названы рядом.

[img]: https://example.com/image.png
"""
        result, _ = self.run_validator(markdown)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[missing-source-link]", result.stdout)

    def test_missing_h1_title_is_structural_error(self) -> None:
        markdown = """*Актуально на 1 сентября 2026 года.*

## Коротко

Главный вывод подтверждён [источником](https://example.com/source). Границы вывода названы рядом.
"""
        result, _ = self.run_validator(markdown)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[missing-title]", result.stdout)

    def test_title_must_be_unique_and_first_visible_element(self) -> None:
        cases = {
            "body-before-title": "Вступление до заголовка.\n\n# Заголовок",
            "two-titles": "# Первый заголовок\n\n# Второй заголовок",
        }
        for label, title_block in cases.items():
            with self.subTest(label=label):
                markdown = f"""{title_block}

*Актуально на 1 сентября 2026 года.*

## Коротко

Главный вывод подтверждён [источником](https://example.com/source). Границы вывода названы рядом.
"""
                result, _ = self.run_validator(markdown)
                self.assertNotEqual(result.returncode, 0)
                self.assertRegex(result.stdout, r"\[(?:misplaced-title|multiple-titles)\]")

    def test_visible_code_or_html_before_title_is_misplaced(self) -> None:
        cases = (
            "```text\nвидимый код\n```",
            "    видимый код",
            "<div>видимый текст</div>",
        )
        for prefix in cases:
            with self.subTest(prefix=prefix):
                markdown = f"""{prefix}

# Заголовок

*Актуально на 1 сентября 2026 года.*

## Коротко

Главный вывод подтверждён [источником](https://example.com/source). Границы вывода названы рядом.
"""
                result, _ = self.run_validator(markdown)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("[misplaced-title]", result.stdout)

    def test_short_answer_must_be_the_first_h2_section(self) -> None:
        markdown = """# Заголовок

*Актуально на 1 сентября 2026 года.*

## Контекст

Сначала идёт [контекст](https://example.com/source).

## Коротко

Главный ответ дан позже. Его границы тоже указаны.
"""
        result, _ = self.run_validator(markdown)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[missing-short-answer]", result.stdout)

    def test_empty_short_answer_is_structural_error(self) -> None:
        markdown = """# Заголовок

*Актуально на 1 сентября 2026 года.*

## Коротко

## Контекст

Основной текст со [ссылкой](https://example.com/source) начинается слишком поздно.
"""
        result, _ = self.run_validator(markdown)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[empty-short-answer]", result.stdout)

    def test_fifteen_h2_sections_allow_a_substantial_article(self) -> None:
        sections = "\n".join(
            f"## Раздел {index}\n\nКороткий текст раздела {index}."
            for index in range(2, 16)
        )
        markdown = VALID_OPENING + "\n" + sections + "\n"
        result, _ = self.run_validator(markdown)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("[too-many-sections]", result.stdout)

    def test_twenty_h2_sections_fail_as_raw_dossier_shape(self) -> None:
        sections = "\n".join(
            f"## Раздел {index}\n\nКороткий текст раздела {index}."
            for index in range(2, 21)
        )
        markdown = VALID_OPENING + "\n" + sections + "\n"
        result, _ = self.run_validator(markdown)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[too-many-sections]", result.stdout)

    def test_visible_internal_research_ids_fail(self) -> None:
        markdown = (
            VALID_OPENING
            + """
## Основной материал

В текст попали QRY-0001, SRC-0002, EVD-0003, CLM-0004, COM-0005, CTR-0006, SEM-0007, CHK-0008, LIN-0009 и RES-20260901T000000Z-ABCDEF12.
"""
        )
        result, _ = self.run_validator(markdown)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[internal-id]", result.stdout)
        for identifier in (
            "QRY-0001", "SRC-0002", "EVD-0003", "CLM-0004", "COM-0005",
            "CTR-0006", "SEM-0007", "CHK-0008", "LIN-0009",
            "RES-20260901T000000Z-ABCDEF12",
        ):
            self.assertIn(identifier, result.stdout)

    def test_visible_internal_snake_case_fields_fail(self) -> None:
        markdown = (
            VALID_OPENING
            + """
## Основной материал

В текст попали audit_status, delivery_status, claim_id, source_id, supporting_evidence_ids, fingerprint_status, accessed_at, lineage_id, semantic_audit_id, provider_diagnostics, semantic_support, current_context и pass_with_warnings.
"""
        )
        result, _ = self.run_validator(markdown)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[internal-field]", result.stdout)
        for field in (
            "audit_status",
            "claim_id",
            "source_id",
            "supporting_evidence_ids",
            "fingerprint_status",
            "accessed_at",
            "lineage_id",
            "semantic_audit_id",
            "delivery_status",
            "provider_diagnostics",
            "semantic_support",
            "current_context",
            "pass_with_warnings",
        ):
            self.assertIn(field, result.stdout)

    def test_plain_russian_status_text_is_not_an_internal_field(self) -> None:
        markdown = (
            VALID_OPENING
            + """
## Основной материал

Статус проверки описан обычными русскими словами. Состояние доставки также понятно редактору.

## Что важно не исказить

- Речь идёт только о проверенном периоде.
"""
        )
        result, _ = self.run_validator(markdown)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("[internal-field]", result.stdout)

    def test_subject_matter_snake_case_is_not_treated_as_bundle_metadata(self) -> None:
        markdown = (
            VALID_OPENING
            + """
## Основной материал

Стиль snake_case — обычное соглашение Python; пример variable_name здесь относится к теме статьи.

## Что важно не исказить

- Это обозначение синтаксического стиля, а не служебное поле исследования.
"""
        )
        result, _ = self.run_validator(markdown)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("[internal-field]", result.stdout)

    def test_spaced_internal_status_labels_fail(self) -> None:
        markdown = (
            VALID_OPENING
            + """
## Основной материал

Audit status: pass. Delivery status: ready with warnings. Provider diagnostics: TinyFish partial.
"""
        )
        result, _ = self.run_validator(markdown)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[internal-field]", result.stdout)
        self.assertIn("Audit status", result.stdout)
        self.assertIn("Delivery status", result.stdout)
        self.assertIn("Provider diagnostics", result.stdout)

    def test_generated_spaced_bundle_field_labels_fail(self) -> None:
        markdown = (
            VALID_OPENING
            + """
## Основной материал

Output profile: editor-ready
Clarity review: pass
Reviewed claim IDs: 2
Claims preserved: true
Report SHA256: abc
Source URLs: https://example.com/source
Resolution status: resolved
"""
        )
        result, _ = self.run_validator(markdown)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[internal-field]", result.stdout)
        for label in (
            "Output profile",
            "Clarity review",
            "Reviewed claim IDs",
            "Claims preserved",
            "Report SHA256",
            "Source URLs",
            "Resolution status",
        ):
            self.assertIn(label, result.stdout)

    def test_short_answer_semantic_prefix_is_accepted(self) -> None:
        markdown = """# Заголовок

*Актуально на 1 сентября 2026 года.*

## Короткий рейтинг

Первое место подтверждено [источником](https://example.com/rating_(current)). Вывод относится только к указанному срезу.

## Что важно не исказить

- Рейтинг нельзя переносить на другой период.
"""
        result, _ = self.run_validator(markdown)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("[missing-short-answer]", result.stdout)

    def test_semantic_prefix_does_not_make_an_empty_answer_valid(self) -> None:
        markdown = """# Заголовок

*Актуально на 1 сентября 2026 года.*

## Короткий рейтинг

## Контекст

Здесь есть [источник](https://example.com/source), но нет короткого ответа.
"""
        result, _ = self.run_validator(markdown)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[empty-short-answer]", result.stdout)

    def test_style_findings_warn_without_failing(self) -> None:
        long_sentence = " ".join(["длинное"] * 31) + "."
        long_paragraph = " ".join(["фрагмент;"] * 81)
        markdown = (
            VALID_OPENING
            + f"""
## Основной материал

Этот claim прошёл audit, но readiness всё ещё требует пояснения.

{long_sentence}

{long_paragraph}
"""
        )
        result, _ = self.run_validator(markdown)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Editor output: PASS WITH WARNINGS", result.stdout)
        self.assertIn("[untranslated-jargon]", result.stdout)
        self.assertIn("[long-sentence]", result.stdout)
        self.assertIn("[long-paragraph]", result.stdout)

    def test_list_continuations_are_measured_as_one_paragraph(self) -> None:
        first_line = " ".join(["слово"] * 20)
        continuation = " ".join(["продолжение"] * 11) + "."
        markdown = (
            VALID_OPENING
            + f"""
## Основной материал

- {first_line}
  {continuation}

- Первое предложение.
  Второе предложение. Третье предложение. Четвёртое предложение. Пятое предложение.
"""
        )
        result, _ = self.run_validator(markdown)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[long-sentence]", result.stdout)
        self.assertIn("[long-paragraph]", result.stdout)

    def test_russian_closing_quotes_do_not_hide_sentence_boundaries(self) -> None:
        markdown = (
            VALID_OPENING
            + """
## Основной материал

«Первое.» «Второе.» «Третье.» «Четвёртое.» «Пятое.»
"""
        )
        result, _ = self.run_validator(markdown)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[long-paragraph]", result.stdout)

    def test_versions_and_decimals_do_not_hide_sentence_length(self) -> None:
        long_prefix = " ".join(["подробное"] * 31)
        markdown = f"""# Заголовок

Материал актуален для клиента 36.4.1 и выборки 3.5%.

## Коротко

[Источник](https://example.com/source) подтверждает версию 36.4. Второе предложение задаёт границы.

## Основной материал

{long_prefix} для версии 36.4 актуально.

## Что важно не исказить

- Сокращение т.е. не завершает предложение само по себе.
"""
        result, _ = self.run_validator(markdown)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[long-sentence]", result.stdout)
        self.assertNotIn("[short-answer-length]", result.stdout)

    def test_short_answer_sentence_count_is_only_a_warning(self) -> None:
        markdown = """# Заголовок

*Актуально на 1 сентября 2026 года.*

## Коротко

Здесь только [одно предложение](https://example.com/source).

## Основной материал

Остальной текст остаётся понятным.
"""
        result, _ = self.run_validator(markdown)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[short-answer-length]", result.stdout)

    def test_missing_as_of_context_is_structural_error(self) -> None:
        markdown = """# Заголовок

## Коротко

Главный вывод подтверждён [источником](https://example.com/source). Границы вывода названы рядом.
"""
        result, _ = self.run_validator(markdown)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[missing-as-of-context]", result.stdout)

    def test_as_of_context_must_be_in_the_opening(self) -> None:
        markdown = """# Заголовок

## Коротко

Главный вывод подтверждён [источником](https://example.com/source). Границы вывода названы рядом.

## Основной материал

Подробности идут после ответа.

## Что важно не исказить

Материал актуален на 1 сентября 2026 года.
"""
        result, _ = self.run_validator(markdown)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[missing-as-of-context]", result.stdout)

    def test_vague_context_markers_are_structural_errors(self) -> None:
        for context in (
            "Материал актуален.",
            "Актуально на.",
            "По состоянию на неизвестный момент.",
            "Материал актуален для всех 3 категорий.",
        ):
            with self.subTest(context=context):
                markdown = f"""# Заголовок

{context}

## Коротко

Главный вывод подтверждён [источником](https://example.com/source). Границы вывода названы рядом.
"""
                result, _ = self.run_validator(markdown)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("[missing-as-of-context]", result.stdout)

    def test_impossible_calendar_dates_are_structural_errors(self) -> None:
        for context in (
            "Актуально на 2026-99-99.",
            "Актуально на 31 февраля 2026 года.",
            "Актуально на 00.00.2026.",
            "Актуально на February 30, 2026.",
        ):
            with self.subTest(context=context):
                markdown = f"""# Заголовок

{context}

## Коротко

Главный вывод подтверждён [источником](https://example.com/source). Границы вывода названы рядом.
"""
                result, _ = self.run_validator(markdown)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("[missing-as-of-context]", result.stdout)

    def test_valid_calendar_dates_are_accepted(self) -> None:
        for context in (
            "Актуально на 2024-02-29.",
            "Актуально на 29.02.2024.",
            "Актуально на 29 февраля 2024 года.",
            "Актуально на February 29, 2024.",
        ):
            with self.subTest(context=context):
                markdown = f"""# Заголовок

{context}

## Коротко

Главный вывод подтверждён [источником](https://example.com/source). Границы вывода названы рядом.
"""
                result, _ = self.run_validator(markdown)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("[missing-as-of-context]", result.stdout)

    def test_explicit_date_independent_scope_is_accepted(self) -> None:
        markdown = """# Заголовок

Вывод не зависит от даты: исследуется устойчивое определение термина.

## Коротко

Главный вывод подтверждён [источником](https://example.com/source). Границы вывода названы рядом.

## Что важно не исказить

- Утверждение относится только к указанному определению.
"""
        result, _ = self.run_validator(markdown)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_code_only_context_does_not_satisfy_as_of_gate(self) -> None:
        for context in (
            "    Материал актуален для клиента 36.4.",
            "`Материал актуален для клиента 36.4.`",
            "```text\nМатериал актуален для клиента 36.4.\n```",
            "<pre>\nМатериал актуален для клиента 36.4.\n</pre>",
        ):
            with self.subTest(context=context):
                markdown = f"""# Заголовок

{context}

## Коротко

Главный вывод подтверждён [источником](https://example.com/source). Границы вывода названы рядом.
"""
                result, _ = self.run_validator(markdown)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("[missing-as-of-context]", result.stdout)

    def test_natural_russian_current_context_marker_is_accepted(self) -> None:
        markdown = """# Заголовок

Материал актуален для клиента 36.4 и баланса 36.2.2.

## Коротко

Главный вывод подтверждён [источником](https://example.com/source). Границы вывода названы рядом.

## Что важно не исказить

- Вывод относится только к указанным версиям.
"""
        result, _ = self.run_validator(markdown)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("[missing-as-of-context]", result.stdout)

    def test_bare_dotted_version_after_context_marker_is_accepted(self) -> None:
        for context in ("Актуально на 36.4.", "Актуально на v36.4.1."):
            with self.subTest(context=context):
                markdown = f"""# Заголовок

{context}

## Коротко

Главный вывод подтверждён [источником](https://example.com/source). Границы вывода названы рядом.
"""
                result, _ = self.run_validator(markdown)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("[missing-as-of-context]", result.stdout)

    def test_missing_source_link_is_structural_error(self) -> None:
        markdown = """# Заголовок

*Актуально на 1 сентября 2026 года.*

## Коротко

Главный вывод дан без прямой ссылки. Границы вывода названы рядом.
"""
        result, _ = self.run_validator(markdown)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[missing-source-link]", result.stdout)

    def test_missing_limitations_is_warning_only(self) -> None:
        result, _ = self.run_validator(VALID_OPENING)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Editor output: PASS WITH WARNINGS", result.stdout)
        self.assertIn("[missing-limitations-section]", result.stdout)

    def test_research_and_game_anglicisms_are_warning_only(self) -> None:
        markdown = (
            VALID_OPENING
            + """
## Основной материал

- pivot и пивот;
- scaling и скейлинг;
- proxy и прокси;
- payoff, enabler и overlay;
- selection bias и survivorship bias;
- presence metric и presence-метрика;
- causal telemetry, confidence cap и source lineage;
- saturation.
"""
        )
        result, _ = self.run_validator(markdown)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[untranslated-jargon]", result.stdout)
        for term in (
            "pivot/пивот",
            "scaling/скейлинг",
            "proxy/прокси",
            "payoff",
            "enabler",
            "overlay",
            "selection bias",
            "survivorship bias",
            "presence metric/метрика",
            "causal telemetry",
            "confidence cap",
            "source lineage",
            "saturation",
        ):
            self.assertIn(term, result.stdout)

    def test_common_game_anglicisms_are_warning_only(self) -> None:
        markdown = (
            VALID_OPENING
            + """
## Основной материал

- deck, decklist и deckstring;
- build и билд;
- mulligan и муллиган;
- matchup и матчап;
- winrate, win rate и винрейт;
- tier list и тир-лист;
- high-roll и хайролл;
- low-roll и лоуролл;
- board и борд;
- lobby и лобби.
"""
        )
        result, _ = self.run_validator(markdown)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[untranslated-jargon]", result.stdout)
        for term in (
            "deck/decklist/deckstring",
            "build/билд",
            "mulligan/муллиган",
            "matchup/матчап",
            "winrate/win rate/винрейт",
            "tier list/тир-лист",
            "high-roll/хайролл",
            "low-roll/лоуролл",
            "board/борд",
            "lobby/лобби",
        ):
            self.assertIn(term, result.stdout)

    def test_tier_alone_does_not_trigger_the_tier_list_warning(self) -> None:
        markdown = (
            VALID_OPENING
            + """
## Основной материал

В названии исходной категории сохранено слово tier.

## Что важно не исказить

- Это подпись категории источника, а не рекомендация использовать англицизм.
"""
        )
        result, _ = self.run_validator(markdown)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("tier list/тир-лист", result.stdout)

    def test_many_or_wide_tables_are_only_warnings(self) -> None:
        tables = []
        for index in range(4):
            tables.append(
                f"""### Таблица {index + 1}

| Один | Два | Три | Четыре | Пять |
| --- | --- | --- | --- | --- |
| 1 | 2 | 3 | 4 | 5 |
"""
            )
        markdown = VALID_OPENING + "\n## Основной материал\n\n" + "\n".join(tables)
        result, _ = self.run_validator(markdown)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[too-many-tables]", result.stdout)
        self.assertIn("[wide-table]", result.stdout)


if __name__ == "__main__":
    unittest.main()
