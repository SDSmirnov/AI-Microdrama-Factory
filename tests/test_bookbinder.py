"""split-book: back matter is not story, windows are sized by words, a bad reply does not crash."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.studio import bookbinder
from lib.studio.bookbinder import _find_split_paragraph, _merge_short, _split_paragraphs, _strip_back_matter, _windows, split_book


def book(chapters: int, paras: int = 3, words: int = 100, notes: int = 0) -> str:
    parts = []
    for c in range(chapters):
        parts.append(f'Глава {c + 1}')
        parts += [f'Абзац {c}-{p} ' + 'слово ' * words for p in range(paras)]
    if notes:
        parts.append('Примечания')
        for n in range(notes):
            parts += [str(n + 1), f'Сноска {n}.']
    return '\n\n'.join(parts)


class Echo:
    """Splits at the end of every window; `bad` first replies are empty."""

    def __init__(self, bad=0, error=False):
        self.bad, self.error, self.calls = bad, error, 0

    def make_json(self, prompt, schema=None):
        self.calls += 1
        if self.calls <= self.bad:
            if self.error:
                raise json.JSONDecodeError('Cannot extract JSON from LLM response', '', 0)
            return {}
        last = prompt.split('## TEXT TO SPLIT\n\n')[1].split('\n\n---\n')[0].split('\n\n')[-1]
        return {'splits': [{'split_after_text': ' '.join(last.split()[:15]), 'cliffhanger_reason': 'x'}]}


class BookbinderTests(unittest.TestCase):
    def test_anchor_matches_despite_punctuation_and_space_variants(self):
        paras = ['— Да, отец.', 'Он ушёл.', '—\u00a0Да, отец.', '«Позже Хидео-сан сказал нам», — что-то ещё']
        self.assertEqual(_find_split_paragraph(paras, '— Да, отец.', 1), 2)
        self.assertEqual(_find_split_paragraph(paras, 'Позже Хидео-сан сказал нам, — что-то', 0), 3)
        self.assertEqual(_find_split_paragraph(paras, 'он ушел', 0), 1)
        self.assertEqual(_find_split_paragraph(paras, '—…', 0), -1)

    def test_numbered_notes_are_dropped_not_chapters(self):
        paras = book(4, notes=48).split('\n\n')
        kept = _strip_back_matter(paras)
        self.assertEqual(kept[-1].split()[0], 'Абзац')
        self.assertNotIn('Примечания', kept)

    def test_notes_heading_in_the_first_half_is_story(self):
        paras = ['Примечания', 'Он писал примечания.'] + book(4).split('\n\n')
        self.assertEqual(_strip_back_matter(paras), paras)

    def test_windows_reach_the_word_budget_on_chapter_boundaries(self):
        paras = book(10, paras=10, words=100).split('\n\n')  # ~1000 words a chapter
        starts = [i for i, p in enumerate(paras) if p.startswith('Глава')] + [len(paras)]
        windows = _windows(paras, starts)
        self.assertEqual(windows[0], (0, 6))   # 6 chapters reach 6000 words
        self.assertEqual(windows[-1][1], 10)    # the rest is the last window
        self.assertEqual([w[0] for w in windows[1:]], [w[1] for w in windows[:-1]])

    def test_empty_reply_is_retried_then_cut_by_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            llm = Echo(bad=1)
            split_book(book(3), llm, '', Path(tmp))
            self.assertEqual(llm.calls, 2)
            llm = Echo(bad=2, error=True)
            with self.assertLogs(bookbinder.logger, 'ERROR'):
                files = split_book(book(6, paras=10, words=100), llm, '', Path(tmp) / 'b')  # ~6000 words
            words = [len(f.read_text(encoding='utf-8').split()) for f in files]
            self.assertEqual(len(files), 2)   # ~6100 words: two even episodes, not 2500+2500+1100
            self.assertTrue(all(2900 <= w <= 3200 for w in words), words)

    def test_reply_and_thinking_budgets_go_to_backends_that_take_them(self):
        seen = []

        class Budgeted(Echo):
            def make_json(self, prompt, schema=None, max_tokens=0, reasoning_tokens=0):
                seen.append((max_tokens, reasoning_tokens))
                return super().make_json(prompt, schema)
        with tempfile.TemporaryDirectory() as tmp:
            split_book(book(3), Budgeted(), '', Path(tmp))
            split_book(book(3), Echo(), '', Path(tmp) / 'b')  # takes neither: no unexpected keyword
        self.assertEqual(set(seen), {(33_000, bookbinder.SPLIT_REASONING_TOKENS)})

    def test_illustration_markers_are_dropped(self):
        text = book(3).replace('Глава 2', 'Глава 2 [Картинка: _02.jpg]') + '\n\n[Картинка: _03.jpg]'
        with tempfile.TemporaryDirectory() as tmp:
            files = split_book(text, Echo(), '', Path(tmp))
            out = '\n'.join(f.read_text(encoding='utf-8') for f in files)
        self.assertNotIn('Картинка', out)
        self.assertIn('Глава 2\n', out)

    def test_one_paragraph_per_line_is_detected(self):
        long = 'Длинный абзац прозы. ' * 12
        per_line = '\n'.join(['Глава 1', long, 'Не могу.', long, long]) + '\n\n' + '\n'.join(['Глава 2', long])
        self.assertEqual(len(_split_paragraphs(per_line)), 7)
        wrapped = 'Строка обычной\nдлины до семидесяти\nсимволов.\n\nВторой абзац\nтоже перенесён.'
        self.assertEqual(len(_split_paragraphs(wrapped)), 2)

    def test_indented_paragraphs_of_hard_wrapped_text_are_split(self):
        libru = ('Гарри Гаррисон. Беглец\n\n\n     Вино было терпким, густым,\nотдающим пылью.\n'
                 '     - Вы приезжий? - спросил хозяин.\n     "Альфа-ромео" медленно выкатилась\nна дорогу.\n'
                 'Last-modified: Sun, 05 Oct 1997 18:21:32 GMT\n\n1000starsspylogranker82\n')
        with tempfile.TemporaryDirectory() as tmp:
            [episode] = split_book(libru, Echo(), '', Path(tmp))
            out = episode.read_text(encoding='utf-8')
        self.assertNotIn('Last-modified', out)
        self.assertNotIn('1000stars', out)
        story = libru.split('Last-modified')[0]
        self.assertEqual(len(_split_paragraphs(story)), 4)
        self.assertEqual(_split_paragraphs(story)[1], 'Вино было терпким, густым,\nотдающим пылью.')

    def test_text_indented_as_a_whole_keeps_its_blank_line_paragraphs(self):
        quoted = '    Строка обычной\n    длины.\n\n    Второй абзац\n    тоже.'
        self.assertEqual(len(_split_paragraphs(quoted)), 2)

    def test_short_episodes_join_a_neighbour(self):
        paras = ['слово ' * 500] * 6  # 500 words each
        self.assertEqual(_merge_short(paras, [1, 3, 5, 6]), [3, 6])   # 500 → next; last 500 → previous
        self.assertEqual(_merge_short(paras, [2, 4, 6]), [2, 4, 6])


if __name__ == '__main__':
    unittest.main()
