"""logic book mode: raw episodes → fixed prose + setup appendix, cached; bible conflicts applied once."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.studio.fixer import _CLAIMS_MARK, _TEXT_MARK, fix_book, fix_book_conflicts

RAW = ('Джо стоял у стола. В следующий миг он прыгнул на пять метров прямо в Джека и отбросил его на три метра '
       'в дверь. Джек застонал. ' + 'Дождь шёл весь вечер. ' * 20)


class FakeLLM:
    def __init__(self, mode='ok'):
        self.mode, self.calls = mode, []

    def make_text(self, prompt, system_prompt=None):
        self.calls.append(prompt)
        text = prompt.rsplit('Текст эпизода:\n\n', 1)[1]
        if 'Мастер сеттинга' in (system_prompt or ''):
            return 'Кабинет: 4 × 5 × 3 м (оценка). Дверь в дальней стене.'
        if 'противоречия между эпизодом' in prompt:
            fixed = text if self.mode != 'rewrite' else 'Совсем другой текст. ' * 30
            if self.mode == 'stray':  # an uncited sentence changed too
                fixed = fixed.replace('Джек застонал.', 'Джек застонало.')
            return f"{_TEXT_MARK}\n{fixed.replace('у стола', 'у окна')}\n{_CLAIMS_MARK}\nстол → окно"
        if self.mode == 'nomarks':
            return text
        if self.mode == 'mixed':  # a decoding slip: Latin letters inside a Russian word
            return f"{_TEXT_MARK}\n{text.replace('Джек застонал', 'Джек zaстонал')}\n{_CLAIMS_MARK}\n"
        if self.mode == 'short':
            return f"{_TEXT_MARK}\nДжо ударил Джека.\n{_CLAIMS_MARK}\n"
        fixed = text.replace('прыгнул на пять метров прямо в Джека и отбросил его на три метра в дверь',
                             'в два шага сократил дистанцию и впечатал Джека спиной в дверь')
        return f"{_TEXT_MARK}\n{fixed}\n{_CLAIMS_MARK}\n«прыгнул на пять метров» → рывок в два шага"


class LogicBookTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.raw, self.out = Path(tmp.name) / 'raw', Path(tmp.name) / 'book'
        self.raw.mkdir()
        (self.raw / 's01e001.txt').write_text(RAW, encoding='utf-8')

    def test_prose_appendix_and_claims_are_separate_files(self):
        self.assertEqual(fix_book(self.raw, self.out, FakeLLM(), workers=1), [])
        prose = (self.out / 's01e001.txt').read_text(encoding='utf-8')
        self.assertIn('в два шага сократил дистанцию', prose)
        self.assertNotIn(_TEXT_MARK, prose)
        self.assertNotIn('→', prose)  # claims stay out of the prose
        self.assertIn('4 × 5 × 3 м', (self.out / 'appendix' / 's01e001.md').read_text(encoding='utf-8'))
        self.assertIn('рывок в два шага', (self.out / 'appendix' / 's01e001.claims.md').read_text(encoding='utf-8'))

    def test_rerun_is_cached_and_keeps_later_edits_until_raw_changes(self):
        fix_book(self.raw, self.out, FakeLLM(), workers=1)
        prose = self.out / 's01e001.txt'
        prose.write_text(prose.read_text(encoding='utf-8') + ' Правка конфликта.', encoding='utf-8')
        llm = FakeLLM()
        fix_book(self.raw, self.out, llm, workers=1)
        self.assertEqual(llm.calls, [])
        self.assertIn('Правка конфликта.', prose.read_text(encoding='utf-8'))
        (self.raw / 's01e001.txt').write_text(RAW + ' Новый абзац.', encoding='utf-8')
        fix_book(self.raw, self.out, FakeLLM(), workers=1)
        self.assertNotIn('Правка конфликта.', prose.read_text(encoding='utf-8'))

    def test_a_word_in_two_scripts_is_put_back(self):
        with self.assertLogs('lib.studio.fixer', 'WARNING') as logs:
            self.assertEqual(fix_book(self.raw, self.out, FakeLLM('mixed'), workers=1), [])
        self.assertIn('Джек застонал.', (self.out / 's01e001.txt').read_text(encoding='utf-8'))
        self.assertIn("'zaстонал' → 'застонал'", logs.output[0])

    def test_unusable_fix_is_not_written_or_cached(self):
        for mode in ('nomarks', 'short'):
            self.assertEqual(fix_book(self.raw, self.out, FakeLLM(mode), workers=1), ['s01e001'])
            self.assertFalse((self.out / 's01e001.txt').exists())
        self.assertEqual(fix_book(self.raw, self.out, FakeLLM(), workers=1), [])  # retried, now fine

    def test_conflicts_are_applied_once_and_bounded(self):
        fix_book(self.raw, self.out, FakeLLM(), workers=1)
        bible = {'conflicts_by_chapter': {'s01e001': [{
            'entity': 'Joe', 'description': 'stands by the window in s01e000',
            'canon': [{'chapter': 's01e000', 'quote': 'у окна', 'fact': 'by the window'}],
            'fix': [{'chapter': 's01e001', 'quote': 'стоял у стола', 'fact': 'by the desk'}]}]}}
        llm = FakeLLM()
        self.assertEqual(fix_book_conflicts(self.out, bible, llm, workers=1), (['s01e001'], []))
        self.assertIn('КАНОН', llm.calls[0])
        self.assertIn('стоял у окна', (self.out / 's01e001.txt').read_text(encoding='utf-8'))
        self.assertIn('Противоречия', (self.out / 'appendix' / 's01e001.claims.md').read_text(encoding='utf-8'))
        llm = FakeLLM()
        self.assertEqual(fix_book_conflicts(self.out, bible, llm, workers=1), ([], []))  # applied before
        self.assertEqual(llm.calls, [])
        bible['conflicts_by_chapter']['s01e001'][0]['description'] = 'other'
        self.assertEqual(fix_book_conflicts(self.out, bible, FakeLLM('rewrite'), workers=1), ([], ['s01e001']))

    BIBLE = {'conflicts_by_chapter': {'s01e001': [{
        'entity': 'Joe', 'description': 'stands by the window in s01e000',
        'canon': [{'chapter': 's01e000', 'quote': 'у окна', 'fact': 'by the window'}],
        'fix': [{'chapter': 's01e001', 'quote': 'стоял у стола', 'fact': 'by the desk'}]}]}}

    def test_a_conflict_fix_changes_only_the_cited_sentences(self):
        fix_book(self.raw, self.out, FakeLLM(), workers=1)
        with self.assertLogs('lib.studio.fixer', 'WARNING') as logs:
            self.assertEqual(fix_book_conflicts(self.out, self.BIBLE, FakeLLM('stray'), workers=1), (['s01e001'], []))
        text = (self.out / 's01e001.txt').read_text(encoding='utf-8')
        self.assertIn('Джо стоял у окна.', text)
        self.assertIn('Джек застонал.', text)
        self.assertTrue(any('1 change(s) outside the cited sentences put back' in m for m in logs.output))

    def test_prose_rewritten_by_logic_gets_its_conflicts_again(self):
        fix_book(self.raw, self.out, FakeLLM(), workers=1)
        fix_book_conflicts(self.out, self.BIBLE, FakeLLM(), workers=1)
        (self.raw / 's01e001.txt').write_text(RAW + ' Новый абзац.', encoding='utf-8')
        fix_book(self.raw, self.out, FakeLLM(), workers=1)
        self.assertIn('у стола', (self.out / 's01e001.txt').read_text(encoding='utf-8'))
        self.assertEqual(fix_book_conflicts(self.out, self.BIBLE, FakeLLM(), workers=1), (['s01e001'], []))
        self.assertIn('у окна', (self.out / 's01e001.txt').read_text(encoding='utf-8'))

    def test_reply_and_thinking_budgets_go_to_backends_that_take_them(self):
        from lib.studio import fixer
        seen = []

        class Budgeted(FakeLLM):
            def make_text(self, prompt, system_prompt=None, max_tokens=0, reasoning_tokens=0):
                seen.append((max_tokens, reasoning_tokens))
                return super().make_text(prompt, system_prompt)
        fix_book(self.raw, self.out, Budgeted(), workers=1)
        fix_book_conflicts(self.out, self.BIBLE, Budgeted(), workers=1)
        self.assertEqual((len(seen), set(seen)), (3, {(fixer.LOGIC_REPLY_TOKENS, fixer.LOGIC_REASONING_TOKENS)}))

    def test_no_raw_episodes_is_an_error(self):
        with self.assertRaises(FileNotFoundError):
            fix_book(self.out, self.out, FakeLLM(), workers=1)


if __name__ == '__main__':
    unittest.main()
