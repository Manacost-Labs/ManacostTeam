import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "teams/article-seo/scripts/seo_check.py"
sys.path.insert(0, str(SCRIPT.parent))

import seo_check

ARTICLE = """
<p>Сетап взрывного урона и менеджмент руки — главные задачи колоды на заклинаниях.</p>
<p><img src="https://hs-manacost.ru/wp-content/uploads/photo_2026-10-01_09-51-18.jpg" alt="photo_2026-10-01_09-51-18" /></p>
<h2>Список карт и код колоды</h2>
<p>Берн Маг держит в руке [hs_card id="CORE_DRG_107"]Аметистового чарокрыла[/hs_card] и ждёт седьмого хода.</p>
<h2>Муллиган</h2>
<p>Ищите дешёвые заклинания. Подробности в <a href="https://hs-manacost.ru/meta/">мета-отчёте</a>.</p>
<h2>Как играть</h2>
<p>Берн Маг копит урон и добивает соперника за один ход, <a href="https://hsreplay.net/">по данным HSReplay</a>.</p>
<p><a href="https://t.me/manacost_ru"><img src="https://hs-manacost.ru/tg.png" alt="" /></a></p>
"""


def seo(**changes):
    data = {
        "title": "Масса урона за один ход — гайд на Берн Мага от TrueBench",
        "description": "Сетап взрывного урона, менеджмент места в руке и сохранение здоровья — непростые задачи. Со всеми справится только самый умелый Берн Маг.",
        "focus_keyword": "Берн Маг",
        "related": ["ОТК Маг", "Маг на заклинаниях", "гайд на мага", "колоды мага"],
        "answer": " ".join(["слово"] * 45),
        "faq": [
            {
                "question": "Какой муллиган у Берн Мага?",
                "answer": 'Ищите [hs_card id="CORE_DRG_107"]Аметистового чарокрыла[/hs_card].',
            }
        ],
        "schema_type": "TechArticle",
        "slug": "massa-urona-za-odin-hod-gajd-na-bern-maga-ot-truebench",
    }
    data.update(changes)
    return data


def statuses(data, article=ARTICLE, title="Масса урона за один ход — гайд на Берн Мага от TrueBench"):
    report = seo_check.run_checks(
        seo_check.parse_article(article),
        data,
        post_title=title,
        categories=[],
        post_type="post",
        site="hs-manacost.ru",
        lexicon=seo_check.Lexicon(),
    )
    return {item["id"]: item for item in report["checks"]}, report


class StemAndWidthTests(unittest.TestCase):
    def test_title_width_matches_plugin_estimate(self):
        self.assertEqual(seo_check.title_width("Масса урона за один ход — гайд на Берн Мага от TrueBench"), 557)

    def test_stemmer_and_game_synonyms(self):
        matcher = seo_check.Matcher(seo_check.Lexicon())
        self.assertEqual(seo_check.stem("колоды"), "колод")
        self.assertTrue(matcher.contains("Лучшая дека приста в патче", "колода жреца"))
        self.assertTrue(matcher.contains("колоды для мага сейчас", "колода мага"))
        self.assertTrue(matcher.contains("Гайд на ДХ", "охотник на демонов"))
        self.assertFalse(matcher.contains("Пала с краю", "паладин"))

    def test_slug_uses_plugin_transliteration(self):
        matcher = seo_check.Matcher(seo_check.Lexicon())
        self.assertFalse(matcher.in_slug("koloda-zhreca", "колода жреца"))
        self.assertTrue(matcher.in_slug("koloda-zhrecza", "колода жреца"))
        self.assertEqual(seo_check.slugify("Берн Маг: гайд"), "bern-mag-gajd")


class CheckTests(unittest.TestCase):
    def test_reports_the_owner_screenshot_findings(self):
        checks, report = statuses(seo())
        self.assertEqual(checks["keyword_in_first_paragraph"]["status"], "red")
        self.assertEqual(checks["keyword_at_title_start"]["status"], "orange")
        self.assertEqual(checks["slug_length"]["status"], "orange")
        self.assertEqual(checks["image_alt"]["status"], "red")
        self.assertEqual(checks["anchor_text"]["status"], "orange")
        self.assertIn("Матчапы", checks["material_sections"]["message"])
        self.assertIn("Замены", checks["material_sections"]["message"])
        self.assertEqual(checks["description_length"]["status"], "green")
        self.assertEqual(report["material"], "guide")

    def test_fixed_fields_turn_green(self):
        checks, _ = statuses(
            seo(
                title="Берн Маг: масса урона за один ход — гайд от TrueBench",
                alts=[
                    {
                        "src": "https://hs-manacost.ru/wp-content/uploads/photo_2026-10-01_09-51-18.jpg",
                        "alt": "Колода Берн Мага — список карт",
                    },
                    {"src": "https://hs-manacost.ru/tg.png", "alt": "Манакост в Telegram"},
                ],
            )
        )
        self.assertEqual(checks["keyword_at_title_start"]["status"], "green")
        self.assertEqual(checks["image_alt"]["status"], "green")
        self.assertEqual(checks["keyword_in_image_alt"]["status"], "green")

    def test_answer_counts_shortcode_inner_text(self):
        text = '[hs_card id="X"]Аметистового чарокрыла[/hs_card] ' + " ".join(["слово"] * 38)
        self.assertEqual(seo_check.answer_words(text), 40)
        checks, _ = statuses(seo(answer="Коротко."))
        self.assertEqual(checks["answer"]["status"], "orange")
        checks, _ = statuses(seo(answer="", schema_type="none"))
        self.assertNotIn("answer", checks)

    def test_field_limits(self):
        checks, _ = statuses(seo(related="а, б, в, г, д", description="Берн Маг коротко."))
        self.assertEqual(checks["related"]["status"], "red")
        self.assertEqual(checks["description_length"]["status"], "orange")
        faq = [{"question": "Вопрос без знака", "answer": '[hs_card id="A"]Карта'}] * 11
        checks, _ = statuses(seo(faq=faq))
        message = checks["faq"]["message"]
        self.assertIn("максимум 10", message)
        self.assertIn("без знака вопроса", message)
        self.assertIn("незакрытый шорткод", message)

    def test_first_paragraph_without_p_uses_first_60_words(self):
        article = "<h2>Муллиган</h2>\nБерн Маг ищет заклинания.\n<img src='a.png' alt='Колода'>"
        checks, _ = statuses(seo(), article=article)
        self.assertEqual(checks["keyword_in_first_paragraph"]["status"], "green")

    def test_markdown_article_and_material_detection(self):
        article = "Берн Маг — колода на заклинаниях.\n\n## Муллиган\n\n- Чарокрыл\n\n## Против агрессии\n\nТекст."
        checks, report = statuses(seo(), article=article, title="Берн Маг на заклинаниях")
        self.assertEqual(report["material"], "guide")
        self.assertEqual(checks["keyword_in_first_paragraph"]["status"], "green")
        self.assertEqual(seo_check.detect_material("Нерф Берн Мага: гайд", [], [], "post"), "patch")
        self.assertEqual(seo_check.detect_material("Колода дня", ["Новости"], [], "post"), "news")


class ManacostNormTests(unittest.TestCase):
    TITLE = "Берн Маг: масса урона за один ход — гайд от TrueBench"

    def test_clean_title_and_colloquial_related_are_green(self):
        checks, report = statuses(seo(title=self.TITLE), title=self.TITLE)
        self.assertEqual(checks["title_not_truncated_or_vague"]["status"], "green")
        self.assertEqual(checks["related_colloquial"]["status"], "green")
        self.assertIn("ОТК Маг", checks["related_colloquial"]["message"])
        self.assertNotIn("guide_preposition", checks)
        # нормы Манакоста не входят в оценку плагина
        self.assertNotIn("title_not_truncated_or_vague", seo_check.WEIGHTS)
        self.assertEqual(report["score_estimate"], statuses(seo(title=self.TITLE, related=[]), title=self.TITLE)[1]["score_estimate"])

    def test_title_dot_title_case_and_guide_na(self):
        title = "Масса Урона За Один Ход — Гайд На Берн Мага."
        checks, _ = statuses(seo(title=title), title=self.TITLE)
        message = checks["title_not_truncated_or_vague"]["message"]
        self.assertEqual(checks["title_not_truncated_or_vague"]["status"], "orange")
        self.assertIn("точка в конце", message)
        self.assertIn("Title Case", message)
        self.assertIn("гайд по", message)

    def test_truncated_title(self):
        for title in ("Лучшие тир-1 существа на", "Лучшие тир-1 существа…", "Лучшие тир-1 существа —"):
            checks, _ = statuses(seo(title=title), title=self.TITLE)
            self.assertIn("обрезанный", checks["title_not_truncated_or_vague"]["message"], title)

    def test_card_and_archetype_names_are_not_title_case(self):
        self.assertEqual(seo_check.title_case_words("Первый ход на Полях сражений: лучшие тир-1 существа"), [])
        self.assertEqual(seo_check.title_case_words("Хэндбафф Рыцарь смерти от Ника — топ-1 Легенды"), [])
        self.assertEqual(seo_check.title_case_words("Квест Маг и Фейс Хант в Вольном формате"), [])
        self.assertEqual(seo_check.title_case_words("Фейс Хант и Мех Паладин в Стандарте"), [])
        self.assertEqual(
            seo_check.title_case_words("Лучший Первый Ход На Полях Сражений"), ["Первый", "Ход", "Сражений"]
        )
        self.assertEqual(
            seo_check.title_case_words("Квест Маг и Миракл Разбойник: Лучшие Колоды"), ["Миракл", "Лучшие", "Колоды"]
        )

    def test_guide_na_is_allowed_only_in_related(self):
        faq = [{"question": "Где гайд на Берн Мага?", "answer": "Это гайд по Берн Магу."}]
        checks, _ = statuses(seo(title=self.TITLE, faq=faq, answer="Короткий гайд на мага."), title="Гайд на Берн Мага")
        message = checks["guide_preposition"]["message"]
        self.assertEqual(checks["guide_preposition"]["status"], "orange")
        for field in ("H1", "краткий ответ", "вопрос 1"):
            self.assertIn(field, message)
        self.assertNotIn("ответ 1", message)
        # в похожих запросах «гайд на мага» из фикстуры — норма
        self.assertEqual(checks["title_not_truncated_or_vague"]["status"], "green")

    def test_related_without_short_colloquial_synonym(self):
        related = ["тир-1 существа Полей сражений", "лучшие существа 1 уровня таверны"]
        checks, _ = statuses(seo(related=related), title=self.TITLE)
        self.assertEqual(checks["related_colloquial"]["status"], "orange")
        checks, _ = statuses(seo(related=related + ["тир-1 существа бг"]), title=self.TITLE)
        self.assertEqual(checks["related_colloquial"]["status"], "green")
        # длинная фраза со сленгом — не короткий синоним
        checks, _ = statuses(seo(related=["как играть на первом ходу в бг новичку"]), title=self.TITLE)
        self.assertEqual(checks["related_colloquial"]["status"], "orange")


class CliTests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, arguments)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )

    def test_card_output_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            article = directory / "article.html"
            article.write_text(ARTICLE, encoding="utf-8")
            fields = directory / "seo.json"
            fields.write_text(json.dumps(seo(), ensure_ascii=False), encoding="utf-8")
            process = self.run_cli(article, "--seo", fields, "--card")
            self.assertEqual(process.returncode, 1, process.stderr)
            self.assertIn("## Вид в поиске", process.stdout)
            self.assertIn("**Чем считать материал для поисковиков:** Гайд", process.stdout)
            fields.write_text("[]", encoding="utf-8")
            process = self.run_cli(article, "--seo", fields)
            self.assertEqual(process.returncode, 2)
            self.assertNotIn("Traceback", process.stderr)
        self.assertEqual(self.run_cli("--slugify", "Колода жреца").stdout.strip(), "koloda-zhrecza")


if __name__ == "__main__":
    unittest.main()
