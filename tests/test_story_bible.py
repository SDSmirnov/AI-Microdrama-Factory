"""Story bible: chunked multi-pass collector, versioned by story time."""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.core.project import Project
from lib.core.schemas import (
    BIBLE_CHUNK_SCHEMA, BIBLE_ENRICH_BATCH_SCHEMA, BIBLE_ENRICH_SCHEMA, BIBLE_GLEAN_SCHEMA, BIBLE_RESOLVE_SCHEMA,
    BIBLE_SETUP_BATCH_SCHEMA, BIBLE_TIMELINE_SCHEMA, CHARACTER_SCHEMA, ROOM_DETAIL_SCHEMA, ROOM_VOCABULARY_CRITIQUE_SCHEMA, ROOM_VOCABULARY_SCHEMA,
)
from lib.studio import archivist
from lib.studio.artist.view_catalog import _ROOM_VIEWS
from lib.studio.archivist import (
    _locate, build_bible, chapter_window, chunk_chapter, entity_block, foreshadowed, load_bible, place_block,
)

CH = {
    's01e001': 'Иван Петрович вошёл в свой кабинет и надел пальто.',
    's01e002': 'Через неделю Петрович сел в коричневую машину, того же цвета, что его пальто и ботинки.',
    's01e003': 'Он вспомнил детство. Он достал револьвер из сейфа, встроенного в стену кабинета.',
}


def ent(ref_name, etype, names, *facts):
    return {'ref_name': ref_name, 'names': names, 'type': etype, 'role': ref_name,
            'facts': [{'kind': k, 'fact': f, 'quote': q, 'explicit': True} for k, f, q in facts]}


def t(label):
    return {'cues': [], 'label': label, 'season': 'autumn', 'month': '', 'time_of_day': '', 'weather': 'rain',
            'flashback': False}


FIRST_READ = {
    's01e001#001': {'time': t('start'), 'entities': [
        ent('Ivan-Petrov', 'Character', ['Иван Петрович'], ('wardrobe', 'wears a coat', 'надел пальто')),
        ent('Detective-Office', 'Room', ['кабинет'], ('layout', 'his own office', 'свой кабинет'))]},
    's01e002#001': {'time': t('a week later'), 'entities': [
        ent('Petrovich', 'Character', ['Петрович'],
            ('wardrobe', 'brown coat and brown shoes', 'того же цвета, что его пальто и ботинки')),
        ent('Petrovich-Car', 'Vehicle', ['машина'], ('appearance', 'brown paint', 'коричневую машину'))]},
    's01e003#001': {'time': t('same week'), 'entities': [
        ent('Ivan-Petrov', 'Character', ['Он'], ('carried', 'revolver', 'достал револьвер'))]},
}
GLEAN = {  # the first read of chapter 3 missed the safe; the re-read finds it (and a bogus quote)
    's01e003#001': [{'entities': [ent('Detective-Office', 'Room', ['кабинет'],
                                      ('fixture', 'steel safe built into the wall', 'сейфа, встроенного в стену'),
                                      ('prop', 'green desk lamp', 'зелёная лампа'))]}],
}
SETUP_READ = {'time': t(''), 'entities': [  # the logic step's appendix: sizes the novel never gives
    ent('Detective-Office', 'Room', ['Кабинет'], ('layout', 'room 4 x 5 x 3 m', 'Кабинет: 4 × 5 × 3 м'))]}
TIMELINE = {'periods': [
    {'id': 'T01', 'order': 1, 'label': 'Week 1', 'season': 'autumn', 'month': '', 'weather': '', 'flashback': False},
    {'id': 'T02', 'order': 2, 'label': 'Week 2', 'season': 'autumn', 'month': '', 'weather': 'rain',
     'flashback': False},
]}
ASSIGN = {'s01e001#001': 'T01', 's01e002#001': 'T02', 's01e003#001': 'T09'}  # T09 unknown → inherits T02


def enrich_for(name, prompt):
    ids = {f: r for r, f in re.findall(r'^  (\S+/\d+) \| \S+ \| \w+ \| \w+ \| (.*?) \|', prompt, re.M)}
    if name == 'Detective-Office':
        return {'visual_desc': 'Small office.', 'conflicts': [], 'variants': [], 'features': [
            {'id': 'Wall Safe', 'description': 'steel safe in the left wall', 'applies_from': 'T01', 'until': '',
             'source': 'stated', 'reason': '', 'refs': [ids.get('steel safe built into the wall', 'r0'), 'r999']}]}
    if name == 'Ivan-Petrov':
        return {'visual_desc': 'Detective.', 'conflicts': [{'description': 'x', 'refs': ['r999']}], 'features': [],
                'variants': [{'label': 'Brown Coat', 'variance': 'brown coat', 'context': 'outdoors',
                              'description': 'Detective in a brown coat and brown shoes.',
                              'time_context': {'from': 'T02', 'to': 'T77'}, 'refs': list(ids.values())}]}
    return {'visual_desc': name, 'features': [], 'variants': [], 'conflicts': []}


class FakeLLM:
    def __init__(self, fail_enrich=False):
        self.calls, self.fail_enrich, self.glean_round = [], fail_enrich, {}

    def make_json(self, prompt, schema):
        self.calls.append((schema, prompt))
        if schema is BIBLE_CHUNK_SCHEMA:
            cid = re.search(r'<FRAGMENT id="([^"]+)"', prompt)[1]
            return json.loads(json.dumps(FIRST_READ[cid] if '@setup' not in cid else SETUP_READ))
        if schema is BIBLE_SETUP_BATCH_SCHEMA:
            return {'notes': [{'id': cid, 'entities': json.loads(json.dumps(SETUP_READ['entities']))}
                              for cid in re.findall(r'<FRAGMENT id="([^"]+)"', prompt)]}
        if schema is BIBLE_GLEAN_SCHEMA:
            cid = re.search(r'<FRAGMENT id="([^"]+)"', prompt)[1]
            i = self.glean_round[cid] = self.glean_round.get(cid, -1) + 1
            rounds = GLEAN.get(cid, [])
            return json.loads(json.dumps(rounds[i])) if i < len(rounds) else {'entities': []}
        if schema is BIBLE_TIMELINE_SCHEMA:
            ids = re.findall(r'^  (s\d+e\d+#\d+) \|', prompt, re.M)
            return {**TIMELINE, 'chunks': [{'chunk': c, 'period': ASSIGN[c]} for c in ids]}
        if schema is BIBLE_RESOLVE_SCHEMA:
            return {'merges': [{'ref_name': 'Ivan-Petrov', 'keys': ['ivan-petrov', 'petrovich', 'ghost']}]}
        if schema is BIBLE_ENRICH_SCHEMA:
            if self.fail_enrich:
                return None
            return enrich_for(re.search(r'references? (?:for|of) (\S+) \(', prompt)[1], prompt)
        if schema is BIBLE_ENRICH_BATCH_SCHEMA:
            if self.fail_enrich:
                return None
            return {'entities': [{'key': m[1], **enrich_for(m[2], b)} for b in self.blocks(prompt)
                                 if (m := re.match(r'ENTITY (\S+): (\S+) \(', b))]}
        if schema is ROOM_VOCABULARY_SCHEMA:
            return {'named_positions': [{'id': 'desk', 'description': 'desk'}]}
        if schema is ROOM_VOCABULARY_CRITIQUE_SCHEMA:
            return None
        if schema is ROOM_DETAIL_SCHEMA:
            return {'enriched_visual_desc': ''}
        raise AssertionError(schema)

    def count(self, schema):
        return sum(s is schema for s, _ in self.calls)

    @staticmethod
    def blocks(prompt):
        return re.findall(r'^ENTITY .*?(?=^ENTITY |^SOURCE EXCERPTS)', prompt, re.M | re.S)

    def enrich_prompts(self):
        """Every description prompt, single or batched."""
        return [p for s, p in self.calls if s in (BIBLE_ENRICH_SCHEMA, BIBLE_ENRICH_BATCH_SCHEMA)]


def write_chapters(root: Path) -> list[Path]:
    paths = []
    for cid, text in CH.items():
        (root / f'{cid}.txt').write_text(text, encoding='utf-8')
        paths.append(root / f'{cid}.txt')
    return paths


class ChunkTests(unittest.TestCase):
    def test_paragraph_aligned_with_short_overlap_and_long_paragraph_cut(self):
        text = '\n\n'.join(['Абзац один. ' * 3, 'Короткий.', 'Длинный абзац ' * 20, 'Конец.'])
        chunks = chunk_chapter('c1', text, size=80)
        self.assertEqual([c.id for c in chunks][:2], ['c1#001', 'c1#002'])
        for c in chunks:
            self.assertEqual(text[c.start:c.start + len(c.text)], c.text)
            self.assertLessEqual(len(c.text), 80 + 80 // 4 + 2)
        self.assertIn('Конец.', chunks[-1].text)
        self.assertTrue(chunks[1].text.startswith('Короткий.'))  # a short last paragraph is repeated

    def test_locate_ignores_punctuation_case_and_yo(self):
        text = 'Он достал револьвер из сейфа, встроенного в стену.'
        self.assertEqual(_locate(text, 'СЕЙФА встроенного   в стену'), text.index('сейфа'))
        self.assertEqual(_locate('ещё раз', 'еще раз'), 0)
        self.assertIsNone(_locate(text, 'зелёная лампа'))
        self.assertEqual(_locate(text, 'достал револьвер... в стену'), text.index('достал'))
        self.assertIsNone(_locate(text, 'в стену… достал'))  # pieces out of order

    def test_placeholders_and_one_off_extras_get_no_ref(self):
        from lib.studio.archivist import _references, needs_ref
        c = archivist.Chunk('c1#001', 'c1', 0, 'Гонец пришёл.')
        extracted = {c.id: {'entities': [ent('None', 'Vehicle', [], ('appearance', 'no car', 'x')),
                                         ent('Messenger', 'Character', ['гонец'], ('appearance', 'came', 'Гонец'))]}}
        refs, cands = _references([c], extracted, {c.id: 'T01'})
        self.assertEqual(list(cands), ['messenger'])
        self.assertFalse(needs_ref({'refs': refs, 'chapters': ['c1'], 'type': 'Character', 'aliases': ['гонец']}))
        self.assertTrue(needs_ref({'refs': refs * 3, 'chapters': ['c1'], 'type': 'Character', 'aliases': ['гонец']}))

    def test_a_lead_named_often_gets_a_ref_without_description(self):
        from lib.studio.archivist import MENTIONS, mentions, needs_ref
        groom = {'refs': [1], 'chapters': ['c1'], 'type': 'Character', 'aliases': ['Жених', 'Жениха']}
        texts = {'c1': 'Жених вошёл. Невеста ждала жениха. Женихов не было. ' * 2}
        self.assertEqual(mentions(groom, texts), 4)  # «Женихов» is another word
        self.assertFalse(needs_ref(groom, texts))
        texts['c1'] += 'Жених. ' * (MENTIONS - 4)
        self.assertTrue(needs_ref(groom, texts))
        self.assertFalse(needs_ref({**groom, 'type': 'Room'}, texts))


class BibleTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.paths = write_chapters(self.root)
        self.bible_dir = self.root / 'story_bible'

    def build(self, llm=None, **kw):
        llm = llm or FakeLLM()
        bible, failed = build_bible(self.paths, llm, self.bible_dir, workers=1, **kw)
        return bible, failed, llm

    def test_gleaning_finds_what_the_first_read_missed_and_stops(self):
        bible, failed, llm = self.build()
        self.assertEqual(failed, [])
        self.assertEqual(bible['entities']['detective-office']['features'][0]['id'], 'wall-safe')
        # ch3: one gain then an empty re-read; ch1 and ch2: one empty re-read each
        self.assertEqual(llm.count(BIBLE_GLEAN_SCHEMA), 4)
        _, _, llm = self.build(gleanings=0, force=True)
        self.assertEqual(llm.count(BIBLE_GLEAN_SCHEMA), 0)

    def test_quote_not_in_text_is_deduced_and_located_quotes_have_offsets(self):
        bible, _, _ = self.build()
        refs = {r['fact']: r for r in bible['entities']['detective-office']['refs']}
        self.assertFalse(refs['green desk lamp']['explicit'])
        self.assertIsNone(refs['green desk lamp']['offset'])
        safe = refs['steel safe built into the wall']
        self.assertTrue(safe['explicit'])
        self.assertTrue(CH['s01e003'][safe['offset']:].startswith('сейфа,'))

    def test_timeline_assigns_periods_and_unknown_period_inherits(self):
        bible, _, _ = self.build()
        self.assertEqual([p['id'] for p in bible['periods']], ['T01', 'T02'])
        self.assertEqual({c['id']: c['periods'] for c in bible['chapters']},
                         {'s01e001': ['T01'], 's01e002': ['T02'], 's01e003': ['T02']})

    def test_resolve_merges_names_and_ignores_unknown_keys(self):
        bible, _, _ = self.build()
        self.assertEqual(set(bible['entities']), {'ivan-petrov', 'detective-office', 'petrovich-car'})
        ivan = bible['entities']['ivan-petrov']
        self.assertEqual(ivan['chapters'], ['s01e001', 's01e002', 's01e003'])
        self.assertIn('Петрович', ivan['aliases'])

    def test_proper_names_in_source_script_give_one_key_and_a_latin_display_name(self):
        class SourceScript(FakeLLM):  # every chunk copies the name, no chunk transliterates it
            def make_json(self, prompt, schema):
                reply = super().make_json(prompt, schema)
                if schema is BIBLE_RESOLVE_SCHEMA:
                    return {'merges': [{'ref_name': 'Иван-Петров', 'keys': ['ivan-petrov', 'petrovich']}]}
                for e in (reply or {}).get('entities') or [] if schema is not BIBLE_ENRICH_BATCH_SCHEMA else []:
                    e['ref_name'] = {'Ivan-Petrov': 'Иван-Петров', 'Petrovich': 'Иван-Петров',
                                     'Petrovich-Car': 'Петрович-Car'}.get(e['ref_name'], e['ref_name'])
                return reply
        bible, failed, _ = self.build(SourceScript())
        self.assertEqual(failed, [])
        self.assertEqual(set(bible['entities']), {'ivan-petrov', 'detective-office', 'petrovich-car'})
        self.assertEqual(bible['entities']['ivan-petrov']['ref_name'], 'Ivan-Petrov')
        self.assertEqual(bible['entities']['ivan-petrov']['chapters'], ['s01e001', 's01e002', 's01e003'])
        self.assertEqual(bible['entities']['petrovich-car']['ref_name'], 'Petrovich-Car')

    def test_name_without_latin_or_cyrillic_letters_is_dropped_with_a_warning(self):
        class Kanji(FakeLLM):
            def make_json(self, prompt, schema):
                reply = super().make_json(prompt, schema)
                for e in (reply or {}).get('entities') or [] if schema is not BIBLE_ENRICH_BATCH_SCHEMA else []:
                    e['ref_name'] = '本願寺' if e['ref_name'] == 'Petrovich-Car' else e['ref_name']
                return reply
        with self.assertLogs('lib.studio.archivist', 'WARNING') as logs:
            bible, _, _ = self.build(Kanji())
        self.assertNotIn('petrovich-car', bible['entities'])
        self.assertTrue(any('本願寺' in m and 'dropped' in m for m in logs.output))

    def test_resolve_rows_hint_at_names_shared_across_inflections(self):
        from lib.studio.archivist import _resolve
        cand = lambda *names: {'ref_name': names[0], 'types': {'Character': 1}, 'names': set(names), 'roles': [],
                               'refs': []}
        cands = {'investigator': cand('дознавателя'), 'seki-osamu': cand('Сэки Осаму', 'Дознаватель'),
                 'hideo': cand('Хидео')}
        llm = FakeLLM()
        _resolve(cands, llm, self.bible_dir / '.cache', force=False)
        prompt = llm.calls[0][1]
        self.assertRegex(prompt, r'investigator \| .* \| seki-osamu\n')
        self.assertRegex(prompt, r'seki-osamu \| .* \| investigator\n')
        self.assertRegex(prompt, r'hideo \| Хидео \| Хидео \|  \| 0 \| \n')

    def test_rooms_and_outdoor_places_are_resolved_together_with_spelling_hints(self):
        from lib.studio.archivist import _resolve
        cand = lambda name, t: {'ref_name': name, 'types': {t: 1}, 'names': {name}, 'roles': [], 'refs': []}
        cands = {'toryumon-house-yard': cand('Торюмон-House-Yard', 'Room'),
                 'toryomon-house-yard': cand('Toryomon-House-Yard', 'Outdoor'), 'ivan': cand('Иван', 'Character')}
        llm = FakeLLM()
        _resolve(cands, llm, self.bible_dir / '.cache', force=False)
        place = next(p for _, p in llm.calls if 'place (room or outdoor area) list' in p)
        self.assertRegex(place, r'toryumon-house-yard \| .* \| toryomon-house-yard\n')
        self.assertRegex(place, r'toryomon-house-yard \| .* \| toryumon-house-yard\n')
        self.assertNotIn('ivan', place)

    def test_resolve_names_common_nouns_and_bare_keys_but_never_twice(self):
        from lib.studio.archivist import _resolve
        cand = lambda name, n: {'ref_name': name, 'types': {'Room': 1}, 'names': {name}, 'roles': [],
                                'refs': [None] * n}
        cands = {'sad': cand('Сад', 3), 'podval': cand('Подвал', 2), 'kryltso': cand('Крыльцо', 1),
                 'toryumon-garden': cand('Toryumon-Garden', 1), 'pech': cand('Печь', 1)}

        class Names(FakeLLM):
            def make_json(self, prompt, schema):
                self.calls.append((schema, prompt))
                return {'merges': [{'ref_name': 'sad', 'keys': ['sad', 'toryumon-garden']}],
                        'names': [{'key': 'podval', 'ref_name': 'Basement'},
                                  {'key': 'kryltso', 'ref_name': 'Toryumon-Garden'},  # taken by the garden
                                  {'key': 'pech', 'ref_name': 'stove'}, {'key': 'ghost', 'ref_name': 'Ghost'}]}
        groups = _resolve(cands, Names(), self.bible_dir / '.cache', force=False)
        self.assertEqual({k: g['ref_name'] for k, g in groups.items()},
                         {'sad': 'Toryumon-Garden', 'podval': 'Basement', 'kryltso': 'Крыльцо', 'pech': 'Печь'})
        self.assertEqual(groups['sad']['keys'], ['sad', 'toryumon-garden'])

    def test_safe_named_in_week_2_is_drawn_from_week_1(self):
        bible, _, _ = self.build()
        office = bible['entities']['detective-office']
        safe = office['features'][0]
        self.assertEqual((safe['applies_from'], safe['first_stated']), ('T01', 'T02'))
        self.assertEqual(len(safe['refs']), 1)  # r999 is not a reference of this entity
        self.assertEqual(foreshadowed(office, {'T01': 0, 'T02': 1}), [safe])
        loaded = load_bible(self.bible_dir)
        block = entity_block(loaded, loaded['entities']['detective-office'], chapter_window(loaded, 's01e001'))
        self.assertIn('[wall-safe]', block)
        self.assertIn('first named later (Week 2), must already be visible', block)
        self.assertIn('[wall-safe]', place_block(bible, 'Detective-Office-View-From-Entrance'))

    def test_variant_is_versioned_by_story_time(self):
        bible, _, _ = self.build()
        ivan = bible['entities']['ivan-petrov']
        v = ivan['variants'][0]
        self.assertEqual((v['label'], v['time_context']), ('brown-coat', {'from': 'T02', 'to': 'T02'}))
        self.assertEqual(ivan['conflicts'], [])  # cites no reference of his: no clash
        self.assertNotIn('brown-coat', entity_block(bible, ivan, chapter_window(bible, 's01e001')))  # week 1
        self.assertIn('variant brown-coat', entity_block(bible, ivan, chapter_window(bible, 's01e002')))

    def test_enrich_reads_source_excerpts(self):
        _, _, llm = self.build()
        prompt = next(p for p in llm.enrich_prompts() if 'Detective-Office' in p)
        self.assertIn('Он достал револьвер из сейфа, встроенного в стену кабинета.', prompt)
        self.assertIn('ENTITY detective-office: Detective-Office (Room); role: Detective-Office; FIRST period: T01',
                      prompt)
        with mock.patch.object(archivist, 'ENRICH_BATCH', 1):
            _, _, llm = self.build(force=True)
        prompt = next(p for s, p in llm.calls if s is BIBLE_ENRICH_SCHEMA and 'for Detective-Office' in p)
        self.assertIn('Он достал револьвер из сейфа, встроенного в стену кабинета.', prompt)
        self.assertIn('FIRST period (T01)', prompt)

    def test_big_entity_is_enriched_in_parts_then_merged(self):
        with mock.patch.object(archivist, 'ENRICH_BUDGET', 60):
            bible, _, llm = self.build()
        prompts = [p for s, p in llm.calls if s is BIBLE_ENRICH_SCHEMA and 'Ivan-Petrov' in p]
        self.assertTrue(any('PART 1 of' in p for p in prompts))
        self.assertTrue(any('merging partial versioned references' in p for p in prompts))
        self.assertEqual(bible['entities']['ivan-petrov']['variants'][0]['label'], 'brown-coat')

    def test_second_run_is_fully_cached_and_change_reruns_its_chunk(self):
        bible, _, _ = self.build()
        self.assertIn('s01e003#001/2', {r['id'] for r in bible['entities']['detective-office']['refs']})
        _, _, llm = self.build()
        self.assertEqual(llm.calls, [])
        self.paths[0].write_text(CH['s01e001'] + ' Дождь.', encoding='utf-8')
        _, _, llm = self.build()
        reread = [p for s, p in llm.calls if s is BIBLE_CHUNK_SCHEMA]
        self.assertEqual(len(reread), 1)
        self.assertIn('<FRAGMENT id="s01e001#001"', reread[0])
        # chapter 1 changed: the office's references elsewhere keep their ids, so only entities whose
        # chapter-1 excerpt changed are re-enriched — the car (chapter 2 only) is not
        enriched = llm.enrich_prompts()
        self.assertTrue(any('Detective-Office' in p for p in enriched))
        self.assertFalse(any('Petrovich-Car' in p for p in enriched))

    def test_failed_merge_keeps_the_parts(self):
        class NoMerge(FakeLLM):
            def make_json(self, prompt, schema):
                return None if 'merging partial versioned references' in prompt else super().make_json(prompt, schema)
        with mock.patch.object(archivist, 'ENRICH_BUDGET', 60), self.assertLogs('lib.studio.archivist', 'ERROR'):
            bible, _, _ = self.build(NoMerge())
        ivan = bible['entities']['ivan-petrov']
        self.assertGreater(ivan['parts'], 1)
        self.assertFalse(ivan['consolidated'])
        self.assertEqual(ivan['visual_desc'], 'Detective.')                 # a part's description, not raw facts
        self.assertIn('brown-coat', [v['label'] for v in ivan['variants']])

    def test_a_changed_re_read_prompt_re_reads_every_chunk(self):
        self.build()
        reword = archivist._glean_prompt
        with mock.patch.object(archivist, '_glean_prompt', lambda c, found: 'Reworded. ' + reword(c, found)):
            _, _, llm = self.build()
        self.assertEqual(llm.count(BIBLE_CHUNK_SCHEMA), 3)

    def test_a_changed_resolve_prompt_resolves_again(self):
        self.build()
        reword = archivist._resolve_prompt
        with mock.patch.object(archivist, '_resolve_prompt', lambda *a: 'Reworded. ' + reword(*a)):
            _, _, llm = self.build()
        self.assertEqual(llm.count(BIBLE_RESOLVE_SCHEMA), 1)

    def test_failed_enrich_keeps_raw_references(self):
        bible, _, _ = self.build(FakeLLM(fail_enrich=True))
        office = bible['entities']['detective-office']
        self.assertFalse(office['consolidated'])
        self.assertTrue(any('safe' in f['description'] for f in office['features']))

    def test_small_entities_share_one_call_and_describe_as_alone(self):
        bible, _, llm = self.build()
        self.assertEqual((llm.count(BIBLE_ENRICH_BATCH_SCHEMA), llm.count(BIBLE_ENRICH_SCHEMA)), (1, 0))
        self.assertEqual(len(llm.blocks(llm.enrich_prompts()[0])), 3)
        self.bible_dir = self.root / 'solo'
        with mock.patch.object(archivist, 'ENRICH_BATCH', 1):
            solo, _, llm = self.build()
        self.assertEqual((llm.count(BIBLE_ENRICH_BATCH_SCHEMA), llm.count(BIBLE_ENRICH_SCHEMA)), (0, 3))
        self.assertEqual(bible['entities'], solo['entities'])

    def test_a_batch_answer_and_a_solo_answer_are_one_cache_entry(self):
        self.build()
        with mock.patch.object(archivist, 'ENRICH_BATCH', 1):
            _, _, llm = self.build()
        self.assertEqual(llm.enrich_prompts(), [])
        self.bible_dir = self.root / 'solo-first'
        with mock.patch.object(archivist, 'ENRICH_BATCH', 1):
            self.build()
        _, _, llm = self.build()
        self.assertEqual(llm.enrich_prompts(), [])

    def test_batches_hold_at_most_enrich_batch_entities_within_the_budget(self):
        bible, _, _ = self.build()
        cost = {k: sum(map(archivist._cost, e['refs'])) for k, e in bible['entities'].items()}
        self.bible_dir = self.root / 'two'
        with mock.patch.object(archivist, 'ENRICH_BATCH', 2):
            _, _, llm = self.build()
        batch = next(p for s, p in llm.calls if s is BIBLE_ENRICH_BATCH_SCHEMA)
        self.assertEqual(re.findall(r'^ENTITY (\S+):', batch, re.M), ['detective-office', 'ivan-petrov'])
        self.assertEqual([p for s, p in llm.calls if s is BIBLE_ENRICH_SCHEMA and 'for Petrovich-Car' in p],
                         [p for s, p in llm.calls if s is BIBLE_ENRICH_SCHEMA])  # the lone one goes alone
        self.bible_dir = self.root / 'tight'
        budget = max(cost.values()) + min(cost.values())
        with mock.patch.object(archivist, 'ENRICH_BUDGET', budget):
            _, _, llm = self.build()
        for p in llm.enrich_prompts():
            keys = re.findall(r'^ENTITY (\S+):', p, re.M)
            self.assertLessEqual(sum(cost[k] for k in keys), budget)

    def test_an_entity_the_batch_drops_or_garbles_is_described_alone(self):
        class Sloppy(FakeLLM):
            def make_json(self, prompt, schema):
                reply = super().make_json(prompt, schema)
                if schema is BIBLE_ENRICH_BATCH_SCHEMA:
                    reply['entities'] = [{**e, 'features': 'safe'} if e['key'] == 'detective-office' else e
                                         for e in reply['entities'] if e['key'] != 'petrovich-car']
                    reply['entities'].append({'key': 'ghost', 'visual_desc': 'Ghost.'})
                return reply
        bible, _, llm = self.build(Sloppy())
        alone = re.findall(r'references? for (\S+) \(', '\n'.join(p for s, p in llm.calls if s is BIBLE_ENRICH_SCHEMA))
        self.assertEqual(sorted(alone), ['Detective-Office', 'Petrovich-Car'])
        self.assertEqual(bible['entities']['petrovich-car']['visual_desc'], 'Petrovich-Car')
        self.assertEqual(bible['entities']['detective-office']['features'][0]['id'], 'wall-safe')
        self.assertNotIn('ghost', bible['entities'])

    def test_a_failed_batch_falls_back_to_one_call_each(self):
        class NoBatch(FakeLLM):
            def make_json(self, prompt, schema):
                reply = super().make_json(prompt, schema)
                return None if schema is BIBLE_ENRICH_BATCH_SCHEMA else reply
        bible, _, llm = self.build(NoBatch())
        self.assertEqual((llm.count(BIBLE_ENRICH_BATCH_SCHEMA), llm.count(BIBLE_ENRICH_SCHEMA)), (1, 3))
        self.assertFalse(any(e.get('consolidated') is False for e in bible['entities'].values()))

    def test_a_batch_item_resting_on_another_entitys_references_is_dropped(self):
        class Swapped(FakeLLM):
            def make_json(self, prompt, schema):
                reply = super().make_json(prompt, schema)
                if schema is BIBLE_ENRICH_BATCH_SCHEMA:
                    ids = {re.match(r'ENTITY (\S+):', b)[1]: re.findall(r'^  (\S+/\d+) \|', b, re.M)
                           for b in self.blocks(prompt)}
                    office = next(e for e in reply['entities'] if e['key'] == 'detective-office')
                    feature = {'description': 'brown coat', 'applies_from': 'T01', 'until': '', 'source': 'stated',
                               'reason': ''}
                    office['features'] += [{**feature, 'id': 'moved', 'refs': ids['ivan-petrov']},
                                           {**feature, 'id': 'mixed', 'refs': ids['ivan-petrov'][:1]
                                            + ids['detective-office'][:1]}]
                return reply
        with self.assertLogs('lib.studio.archivist', 'WARNING') as logs:
            bible, _, _ = self.build(Swapped())
        office = bible['entities']['detective-office']
        own = {r['id'] for r in office['refs']}
        self.assertEqual([f['id'] for f in office['features']], ['wall-safe', 'mixed'])
        self.assertTrue(set(office['features'][1]['refs']) <= own)
        self.assertTrue(any("1 item(s) resting on another entity's references dropped" in m for m in logs.output))

    def test_forced_run_describes_each_entity_once(self):
        self.build()
        _, _, llm = self.build(force=True)
        self.assertEqual((llm.count(BIBLE_ENRICH_BATCH_SCHEMA), llm.count(BIBLE_ENRICH_SCHEMA)), (1, 0))

    def test_reworded_period_labels_do_not_redescribe_entities(self):
        class Reworded(FakeLLM):
            def make_json(self, prompt, schema):
                reply = super().make_json(prompt, schema)
                if schema is BIBLE_TIMELINE_SCHEMA:
                    reply['periods'] = [{**p, 'label': f"{p['label']} (reworded)"} for p in reply['periods']]
                return reply
        self.build()
        for f in (self.bible_dir / '.cache' / 'timeline').iterdir():
            f.unlink()
        bible, _, llm = self.build(Reworded())
        self.assertEqual(llm.count(BIBLE_TIMELINE_SCHEMA), 1)
        self.assertEqual(llm.enrich_prompts(), [])
        self.assertEqual(bible['periods'][0]['label'], 'Week 1 (reworded)')

    def test_an_ungrounded_reply_is_drawn_again_then_fails_its_chunk(self):
        loop = {'time': t('a week later'), 'entities': [ent('Petrovich', 'Character', ['Петрович'], *(
            ('carried', f'holds item {i}', f'сейф в стене {i}') for i in range(4)))]}

        class Looping(FakeLLM):
            def __init__(self, bad):
                super().__init__()
                self.bad = bad

            def make_json(self, prompt, schema):
                reply = super().make_json(prompt, schema)
                if schema is BIBLE_CHUNK_SCHEMA and '<FRAGMENT id="s01e002#001"' in prompt and self.bad:
                    self.bad -= 1
                    return json.loads(json.dumps(loop))
                return reply
        with mock.patch.object(archivist, 'GROUNDED_MIN', 3):
            with self.assertLogs('lib.studio.archivist', 'ERROR') as logs:
                bible, failed, llm = self.build(Looping(1))
            self.assertEqual(failed, [])
            self.assertTrue(any('s01e002#001: ungrounded reply 1/2 (0/4 quotes in the text)' in m for m in logs.output))
            self.assertIn('petrovich-car', bible['entities'])
            self.bible_dir = self.root / 'loops'
            with self.assertLogs('lib.studio.archivist', 'ERROR'):
                bible, failed, _ = self.build(Looping(2))
        self.assertEqual(failed, ['s01e002#001'])
        self.assertNotIn('petrovich-car', bible['entities'])
        self.assertFalse((self.bible_dir / '.cache' / 'chunks' / 's01e002_001.json').exists())

    def appendices(self, *chapters):
        (self.root / 'appendix').mkdir(exist_ok=True)
        for ch in chapters:
            (self.root / 'appendix' / f'{ch}.md').write_text('Кабинет: 4 × 5 × 3 м (оценка).', encoding='utf-8')

    def test_setup_notes_are_read_together_and_answer_as_alone(self):
        self.appendices('s01e001', 's01e003')
        bible, _, llm = self.build()
        setup_alone = [p for s, p in llm.calls if s is BIBLE_CHUNK_SCHEMA and '@setup' in p]
        self.assertEqual((llm.count(BIBLE_SETUP_BATCH_SCHEMA), setup_alone), (1, []))
        batch = next(p for s, p in llm.calls if s is BIBLE_SETUP_BATCH_SCHEMA)
        self.assertEqual(batch.count('NOT story text'), 2)
        self.assertIn('- Detective-Office (Room): кабинет', batch)
        self.bible_dir = self.root / 'solo'
        with mock.patch.object(archivist, 'SETUP_BATCH', 1):
            solo, _, llm = self.build()
        self.assertEqual(llm.count(BIBLE_SETUP_BATCH_SCHEMA), 0)
        self.assertEqual(bible['entities'], solo['entities'])
        _, _, llm = self.build()  # the solo answers serve the batch: one cache entry per note
        self.assertEqual(llm.calls, [])

    def test_a_setup_note_that_fails_only_warns_and_is_read_next_run(self):
        self.appendices('s01e001', 's01e003')

        class NoNotes(FakeLLM):
            def make_json(self, prompt, schema):
                reply = super().make_json(prompt, schema)
                return None if schema is BIBLE_SETUP_BATCH_SCHEMA or '@setup' in prompt and \
                    schema is BIBLE_CHUNK_SCHEMA and 's01e003@setup' in prompt else reply
        with self.assertLogs('lib.studio.archivist', 'WARNING') as logs:
            bible, failed, _ = self.build(NoNotes())
        self.assertEqual(failed, [])
        self.assertTrue(any('s01e003@setup#001: setup note not read' in m for m in logs.output))
        self.assertNotIn('s01e003@setup#001', {r['chunk'] for e in bible['entities'].values() for r in e['refs']})
        bible, failed, llm = self.build()
        self.assertEqual(failed, [])
        self.assertEqual([re.search(r'<FRAGMENT id="([^"]+)"', p)[1] for s, p in llm.calls if s is BIBLE_CHUNK_SCHEMA],
                         ['s01e003@setup#001'])
        self.assertIn('s01e003@setup#001', {r['chunk'] for e in bible['entities'].values() for r in e['refs']})

    def test_setup_notes_reply_on_a_smaller_budget(self):
        self.appendices('s01e001', 's01e003')
        seen = []

        class Budgeted(FakeLLM):
            def make_json(self, prompt, schema, max_tokens=0, reasoning_tokens=0):
                kind = 'batch' if schema is BIBLE_SETUP_BATCH_SCHEMA else 'note' if '@setup' in prompt and \
                    schema is BIBLE_CHUNK_SCHEMA else 'other'
                seen.append((kind, max_tokens))
                return super().make_json(prompt, schema)
        self.build(Budgeted())
        with mock.patch.object(archivist, 'SETUP_BATCH', 1):
            self.bible_dir = self.root / 'solo'
            self.build(Budgeted())
        self.assertEqual(set(seen), {('batch', 2 * archivist.SETUP_REPLY_TOKENS), ('note', archivist.SETUP_REPLY_TOKENS),
                                     ('other', archivist.MAX_REPLY_TOKENS)})

    def test_a_note_the_setup_batch_drops_is_read_alone(self):
        self.appendices('s01e001', 's01e003')

        class DropsOne(FakeLLM):
            def make_json(self, prompt, schema):
                reply = super().make_json(prompt, schema)
                if schema is BIBLE_SETUP_BATCH_SCHEMA:
                    reply['notes'] = [n for n in reply['notes'] if n['id'] != 's01e003@setup#001']
                return reply
        bible, _, llm = self.build(DropsOne())
        alone = re.findall(r'<FRAGMENT id="([^"]+@setup[^"]*)"',
                           '\n'.join(p for s, p in llm.calls if s is BIBLE_CHUNK_SCHEMA))
        self.assertEqual(alone, ['s01e003@setup#001'])
        self.assertEqual({r['chunk'] for r in bible['entities']['detective-office']['refs'] if r['origin'] == 'setup'},
                         {'s01e001@setup#001', 's01e003@setup#001'})
        _, _, llm = self.build(force=True)  # forced: each note still read once
        self.assertEqual((llm.count(BIBLE_SETUP_BATCH_SCHEMA),
                          sum('@setup' in p for s, p in llm.calls if s is BIBLE_CHUNK_SCHEMA)), (1, 0))

    def test_a_recomputed_timeline_keeps_the_last_builds_period_ids(self):
        class Reuses(FakeLLM):  # returns no periods of its own: assigns the known ones
            def make_json(self, prompt, schema):
                reply = super().make_json(prompt, schema)
                if schema is BIBLE_TIMELINE_SCHEMA:
                    self.timeline_prompt, reply['periods'] = prompt, []
                return reply
        self.build()
        for f in (self.bible_dir / '.cache' / 'timeline').iterdir():
            f.unlink()
        llm = Reuses()
        bible, _, _ = self.build(llm)
        self.assertIn('T02 | 2 | Week 2 | autumn |  | rain', llm.timeline_prompt)
        self.assertEqual([(p['id'], p['label']) for p in bible['periods']], [('T01', 'Week 1'), ('T02', 'Week 2')])
        self.assertEqual(bible['entities']['petrovich-car']['refs'][0]['period'], 'T02')
        (self.bible_dir / 'story_bible.json').unlink()  # the cached timeline needs no old bible
        bible, _, llm = self.build()
        self.assertEqual((llm.count(BIBLE_TIMELINE_SCHEMA), [p['id'] for p in bible['periods']]), (0, ['T01', 'T02']))

    def test_resolve_sees_the_last_builds_merges_as_a_hint(self):
        self.build()
        for f in (self.bible_dir / '.cache' / 'resolve').iterdir():
            f.unlink()
        _, _, llm = self.build()
        prompt = next(p for s, p in llm.calls if s is BIBLE_RESOLVE_SCHEMA)
        self.assertIn('The previous build merged (keep a group unless these rows show it is wrong):\n'
                      '  ivan-petrov + petrovich', prompt)
        self.bible_dir = self.root / 'first'
        _, _, llm = self.build()
        self.assertNotIn('previous build', next(p for s, p in llm.calls if s is BIBLE_RESOLVE_SCHEMA))

    def test_the_world_anchor_reaches_every_read_and_description_and_its_keys(self):
        self.appendices('s01e001', 's01e003')
        world = '- **Analog**: Russia, 1990s\n- **Not in this world**: smartphones'
        with mock.patch.object(archivist, 'ENRICH_BUDGET', 60):  # Ivan in parts + merge: every prompt kind
            _, _, llm = self.build(world=world)
            self.assertTrue(all(llm.count(k) for k in (BIBLE_CHUNK_SCHEMA, BIBLE_GLEAN_SCHEMA,
                                                       BIBLE_SETUP_BATCH_SCHEMA, BIBLE_ENRICH_SCHEMA)))
            for s, p in llm.calls:
                if s not in (BIBLE_TIMELINE_SCHEMA, BIBLE_RESOLVE_SCHEMA):
                    self.assertIn('STORY WORLD — the real place and time this novel builds on:\n' + world, p)
            self.assertTrue(any('merging partial' in p and 'STORY WORLD' in p for p in llm.enrich_prompts()))
            _, _, llm = self.build(world=world)
            self.assertEqual(llm.calls, [])
            _, _, llm = self.build(world=world.replace('1990s', '2020s'))
        self.assertEqual(llm.count(BIBLE_CHUNK_SCHEMA), 3)
        self.assertTrue(any('PART 1 of' in p for p in llm.enrich_prompts()))  # the parts, not only the merges
        self.bible_dir = self.root / 'batched'  # default budget: entities described in a batch
        _, _, llm = self.build(world=world)
        batch = [p for s, p in llm.calls if s is BIBLE_ENRICH_BATCH_SCHEMA]
        self.assertTrue(batch and all('STORY WORLD' in p for p in batch))
        _, _, llm = self.build(world=world.replace('1990s', '2020s'))
        self.assertEqual(llm.count(BIBLE_ENRICH_BATCH_SCHEMA), 1)
        self.bible_dir = self.root / 'no-world'
        _, _, llm = self.build()
        self.assertFalse(any('STORY WORLD' in p for _, p in llm.calls))

    def test_duplicate_chapters_and_missing_bible(self):
        with self.assertRaises(ValueError):
            build_bible(self.paths + self.paths[:1], FakeLLM(), self.bible_dir, workers=1)
        bible, _, _ = self.build()
        self.assertIsNone(chapter_window(bible, 's09e009'))
        self.assertEqual(place_block(bible, 'Nowhere'), '')

    def test_progress_logs_counters_found_items_and_cache_hits(self):
        with self.assertLogs('lib.studio.archivist', level='INFO') as logs:
            self.build()
        out = '\n'.join(logs.output)
        self.assertRegex(out, r'\[chunks 3/3 · \d+m\d\ds · ETA ')
        self.assertIn('s01e003#001: 2 entities, 3 facts (re-reads +3 +0)', out)
        self.assertIn('new: Ivan-Petrov, Detective-Office', out)
        self.assertRegex(out, r'\[time 1/1 .*2 new period\(s\): T01 Week 1, T02 Week 2')
        self.assertRegex(out, r'\[resolve 1/1 .*Character: 2 name\(s\), 1 merge group')
        self.assertIn('Detective-Office (Room): 3 refs → 1 features (1 ⏪), 0 variants, 0 conflicts', out)
        self.assertRegex(out, r'\[enrich 3/3 ')
        with self.assertLogs('lib.studio.archivist', level='INFO') as logs:
            self.build()
        self.assertRegex('\n'.join(logs.output), r'\[chunks 1/3 · .* · ETA \?\] 💾 ')

    def test_setup_appendix_is_a_timeless_outranked_source(self):
        appendix = self.root / 'appendix'
        appendix.mkdir()
        (appendix / 's01e003.md').write_text('Кабинет: 4 × 5 × 3 м (оценка).', encoding='utf-8')
        bible, _, llm = self.build()
        setup = [r for r in bible['entities']['detective-office']['refs'] if r['origin'] == 'setup']
        self.assertEqual([(r['chunk'], r['chapter'], r['period'], r['explicit'], r['offset']) for r in setup],
                         [('s01e003@setup#001', 's01e003', 'T02', False, None)])
        self.assertNotIn('s01e003@setup#001', bible['chapters'][2]['chunks'])
        timeline = next(p for s, p in llm.calls if s is BIBLE_TIMELINE_SCHEMA)
        self.assertNotIn('@setup', timeline)
        office = next(p for p in llm.enrich_prompts() if 'Detective-Office' in p)
        self.assertIn('| layout | setup | room 4 x 5 x 3 m |', office)
        self.assertIn("production consultant's notes", office)
        chunk = next(p for s, p in llm.calls if s is BIBLE_CHUNK_SCHEMA and '@setup' in p)
        self.assertIn('NOT story text', chunk)
        self.assertIn('- Detective-Office (Room): кабинет', chunk)  # the chapter's story cast, gleaned one included
        self.assertEqual(llm.count(BIBLE_GLEAN_SCHEMA), 4)          # notes are read once

    def test_a_setup_note_never_adds_an_entity(self):
        appendix = self.root / 'appendix'
        appendix.mkdir()
        for ch in ('s01e002', 's01e003'):
            (appendix / f'{ch}.md').write_text('Герой стоит босиком.', encoding='utf-8')
        hero = {**SETUP_READ, 'entities': SETUP_READ['entities'] + [
            ent('Hero', 'Character', ['Герой'], ('appearance', 'barefoot', 'босиком'))]}

        class NoCarChapter(FakeLLM):
            def make_json(self, prompt, schema):
                if schema is BIBLE_CHUNK_SCHEMA and '@setup' in prompt:
                    self.calls.append((schema, prompt))
                    return json.loads(json.dumps(hero))
                if schema is BIBLE_CHUNK_SCHEMA and 's01e002#001' in prompt:
                    raise ValueError('cut off')
                return super().make_json(prompt, schema)
        with self.assertLogs('lib.studio.archivist', 'WARNING') as logs:
            bible, _, llm = self.build(NoCarChapter())
        self.assertNotIn('hero', bible['entities'])
        self.assertIn('setup notes of s01e002 wait for their story chunks', '\n'.join(logs.output))
        self.assertEqual([re.search(r'id="([^"]+)"', p)[1] for s, p in llm.calls
                          if s is BIBLE_CHUNK_SCHEMA and '@setup' in p], ['s01e003@setup#001'])

    def test_only_a_clash_of_two_story_facts_from_two_quotes_is_a_conflict(self):
        from lib.studio.archivist import _check_enrich
        refs = [{'id': i, 'period': 'T01', 'fact': f, 'quote': q, 'origin': o} for i, f, q, o in [
            ('a', 'blue eyes', 'голубые глаза', 'story'), ('b', 'brown eyes', 'карие глаза', 'story'),
            ('c', 'Blue eyes.', 'синие глаза', 'story'), ('d', 'forgot his whips', 'Карие глаза!', 'story'),
            ('s', 'grey eyes', 'серые глаза', 'setup')]]
        result = {'features': [], 'variants': [], 'conflicts': [
            {'description': 'eye colour', 'refs': ['a', 'b']},
            {'description': 'None identified. Only one reference exists.', 'refs': ['a', 'b']},
            {'description': 'single', 'refs': ['b']}, {'description': 'same fact', 'refs': ['a', 'c']},
            {'description': 'one sentence cited twice', 'refs': ['b', 'd']},
            {'description': 'setup clash', 'refs': ['a', 's']},
            {'description': 'setup states grey eyes', 'refs': ['a', 'b', 's']}, {'description': '', 'refs': ['a', 'b']}]}
        out = _check_enrich('Ivan', result, refs, {'T01': 0}, 'T01', 'T01')
        self.assertEqual(out['conflicts'], [{'description': 'eye colour', 'refs': ['a', 'b']}])

    def test_descriptions_never_say_what_the_text_does_not(self):
        from lib.studio.archivist import _check_enrich
        desc = ('Elderly monk. Shaved head. Clothing: not specified in the references; robes implied. '
                'Carried items: none permanently carried. No scars or build are specified in the sources. '
                'He does not sob. Clothing is not described in the references.')
        out = _check_enrich('Issen', {'visual_desc': desc, 'features': [], 'conflicts': [], 'variants': [
            {'label': 'wet', 'description': 'Soaked robe. Footwear is not mentioned.', 'time_context': {}}]},
            [], {'T01': 0}, 'T01', 'T01')
        self.assertEqual(out['visual_desc'], 'Elderly monk. Shaved head. Robes implied. He does not sob.')
        self.assertEqual(out['variants'][0]['description'], 'Soaked robe.')
        for given, kept in [  # clause by clause; what is said stays, punctuated
            ('A knife. No handle colour is stated in the source; it is carried by Raiden.', 'A knife. It is carried by Raiden.'),
            ('Muramasa (occult; no manifestation described). A scabbard.', 'Muramasa (occult). A scabbard.'),
            ('A bowl; the salt is dry, the bowl is small, and its colour is not stated.', 'A bowl; the salt is dry, the bowl is small.'),
            ('Its material, colour, and position are not specified.', ''),
            ('A wooden stick with no stated length, swung at the fence.', 'A wooden stick with no stated length, swung at the fence.')]:
            self.assertEqual(archivist._said(given), kept)

    def test_conflicts_go_to_the_later_chapters_never_inside_one(self):
        from lib.studio.archivist import conflicts_by_chapter
        refs = [{'id': 'a', 'chapter': 'c1', 'quote': 'голубые глаза', 'fact': 'blue eyes', 'origin': 'story'},
                {'id': 'b', 'chapter': 'c3', 'quote': 'карие глаза', 'fact': 'brown eyes', 'origin': 'story'},
                {'id': 's', 'chapter': 'c2', 'quote': 'x', 'fact': 'grey eyes', 'origin': 'setup'}]
        entities = {'ivan': {'ref_name': 'Ivan', 'refs': refs, 'conflicts': [
            {'description': 'eye colour', 'refs': ['b', 'a', 's']},
            {'description': 'inside c3 only', 'refs': ['b']}, {'description': 'uncited', 'refs': []}]}}
        out = conflicts_by_chapter(entities, ['c1', 'c2', 'c3'])
        self.assertEqual(list(out), ['c3'])
        [first] = out['c3']  # the one inside c3 has no canon: left to a human, not the fixer
        self.assertEqual(([r['quote'] for r in first['canon']], [r['quote'] for r in first['fix']]),
                         (['голубые глаза'], ['карие глаза']))

    def test_a_looping_reply_fails_its_chunk_not_the_build(self):
        class Looping(FakeLLM):
            def make_json(self, prompt, schema):
                if schema is BIBLE_CHUNK_SCHEMA and 's01e002#001' in prompt:
                    raise json.JSONDecodeError('Cannot extract JSON from LLM response', '{"fixture": "none", ', 0)
                return super().make_json(prompt, schema)
        with self.assertLogs('lib.studio.archivist', 'ERROR'):
            bible, failed, _ = self.build(Looping())
        self.assertEqual(failed, ['s01e002#001'])
        self.assertIn('detective-office', bible['entities'])      # the other chunks made it
        self.assertNotIn('petrovich-car', bible['entities'])      # only chapter 2 had the car
        _, failed, _ = self.build()                                # re-run retries only the failed chunk
        self.assertEqual(failed, [])

    def test_reply_and_thinking_budgets_go_to_backends_that_take_them(self):
        seen = []

        class Budgeted(FakeLLM):
            def make_json(self, prompt, schema, max_tokens=0, reasoning_tokens=0):
                seen.append((max_tokens, reasoning_tokens))
                return super().make_json(prompt, schema)
        self.build(Budgeted())
        self.assertEqual(set(seen), {(archivist.MAX_REPLY_TOKENS, archivist.REASONING_TOKENS)})
        self.build(force=True)  # FakeLLM takes neither: no unexpected keyword

    def test_an_unusable_reply_is_drawn_once_more(self):
        class Flaky(FakeLLM):
            bad = 1

            def make_json(self, prompt, schema):
                if schema is BIBLE_CHUNK_SCHEMA and 's01e002#001' in prompt and self.bad:
                    self.bad -= 1
                    raise json.JSONDecodeError('Unterminated string', '{"entities": [', 14)
                return super().make_json(prompt, schema)
        with self.assertLogs('lib.studio.archivist', 'ERROR'):
            bible, failed, llm = self.build(Flaky())
        self.assertEqual(failed, [])
        self.assertIn('petrovich-car', bible['entities'])

    def test_a_failed_re_read_is_reported_and_not_cached(self):
        class FailedGlean(FakeLLM):
            def make_json(self, prompt, schema):
                return None if schema is BIBLE_GLEAN_SCHEMA and 's01e003#001' in prompt else \
                    super().make_json(prompt, schema)
        with self.assertLogs('lib.studio.archivist', 'ERROR') as logs:
            bible, failed, _ = self.build(FailedGlean())
        self.assertEqual(failed, ['s01e003#001'])
        self.assertIn('a re-read failed', '\n'.join(logs.output))
        self.assertIn('ivan-petrov', bible['entities'])  # the first read is used
        _, failed, llm = self.build()                     # and the chunk is read again next time
        self.assertEqual(failed, [])
        self.assertEqual([re.search(r'id="([^"]+)"', p)[1] for s, p in llm.calls if s is BIBLE_CHUNK_SCHEMA],
                         ['s01e003#001'])

    def test_placeholder_facts_are_dropped(self):
        from lib.studio.archivist import _references
        c = archivist.Chunk('c1#001', 'c1', 0, 'Нет, я дознаватель.')
        e = ent('Investigator', 'Character', ['я'], ('carried', 'identifies as investigator', 'я дознаватель'))
        e['facts'] += [{'kind': 'fixture', 'fact': 'none', 'quote': '', 'explicit': False}] * 50 + [
            {'kind': 'appearance', 'fact': 'no facial or hair details are given', 'quote': '', 'explicit': False},
            {'kind': 'appearance', 'fact': 'no beard', 'quote': '', 'explicit': False}]
        refs, _ = _references([c], {c.id: {'entities': [e]}}, {c.id: 'T01'})
        self.assertEqual([r['fact'] for r in refs], ['identifies as investigator', 'no beard'])

    def test_names_the_fragment_does_not_contain_are_dropped(self):
        from lib.studio.archivist import _references
        c = archivist.Chunk('c1#001', 'c1', 0, 'Иван Петрович говорил с Петровичем-младшим.')
        e = ent('Ivan', 'Character', ['Иван Петрович', 'Петрович', 'Ivan-Father', 'Петрович +2', '+1', 'Иван?'],
                ('appearance', 'talks', 'говорил'))
        _, cands = _references([c], {c.id: {'entities': [e]}}, {c.id: 'T01'})
        self.assertEqual(cands['ivan']['names'], {'Иван Петрович', 'Петрович', 'Иван?'})  # inflected, punctuated

    def test_a_factless_entity_joins_the_one_entity_holding_its_names(self):
        from lib.studio.archivist import _absorb_bare

        def cand(names, refs=(), etype='Character', role=''):
            return {'ref_name': names[0], 'types': {etype: 1}, 'names': set(names), 'roles': [role] if role else [],
                    'refs': list(refs)}
        cands = {'hideo': cand(['Хидео', 'Хидео-сан'], ['r1']), 'torymon': cand(['Торюмон Хидео']),
                 'toriiomon-hideo': cand(['Торюмоном Хидео', 'Хидео-сан']),
                 'seki': cand(['Сэки']),                                          # two holders: ambiguous
                 'seki-osamu': cand(['Сэки Осаму'], ['r2']), 'seki-ryo': cand(['Сэки Рё'], ['r3']),
                 'mizuki-san': cand(['Мизуки-сан']),                              # no holder
                 'hideo-house': cand(['Хидео'], etype='Room'),                    # another kind
                 'izao': cand(['Изао']), 'izao-father': cand(['Изао', 'отец'])}  # holders without facts
        groups = {k: {'ref_name': k, 'keys': [k]} for k in cands if k not in ('torymon',)}
        groups['hideo']['keys'].append('torymon')  # resolve merged it: its names count for the group
        _absorb_bare(groups, cands)
        self.assertEqual(sorted(groups), ['hideo', 'hideo-house', 'izao', 'izao-father', 'mizuki-san', 'seki',
                                          'seki-osamu', 'seki-ryo'])
        self.assertEqual(groups['hideo'], {'ref_name': 'hideo', 'keys': ['hideo', 'torymon', 'toriiomon-hideo']})

    def test_bible_names_have_one_owner(self):
        class Misread(FakeLLM):  # Ivan also called 'кабинет'; ch2 names Ivan and the car again with no facts
            def make_json(self, prompt, schema):
                reply = super().make_json(prompt, schema)
                if schema is BIBLE_CHUNK_SCHEMA and 'id="s01e001#001"' in prompt:
                    reply['entities'][0]['names'].append('кабинет')
                if schema is BIBLE_CHUNK_SCHEMA and 'id="s01e002#001"' in prompt:
                    reply['entities'] += [ent('Petrovitch', 'Character', ['Петрович']),
                                          ent('Petrovich-Brown-Car', 'Vehicle', ['машину'])]
                if schema is BIBLE_RESOLVE_SCHEMA:
                    reply['names'] = [{'key': 'petrovich-brown-car', 'ref_name': 'Brown-Car'}]
                return reply
        bible, _, _ = self.build(Misread())
        e = bible['entities']
        self.assertEqual(sorted(e), ['detective-office', 'ivan-petrov', 'petrovich-car'])
        self.assertEqual(e['petrovich-car']['ref_name'], 'Petrovich-Car')  # the absorbed spelling never names it
        self.assertEqual(e['petrovich-car']['aliases'], ['машина', 'машину'])
        self.assertIn('Петрович', e['ivan-petrov']['aliases'])
        self.assertNotIn('кабинет', e['ivan-petrov']['aliases'] + e['detective-office']['aliases'])

    def test_a_feature_is_stated_only_when_it_cites_a_located_story_quote(self):
        from lib.studio.archivist import _check_enrich
        refs = [{'id': 'q', 'period': 'T01', 'explicit': True}, {'id': 's', 'period': 'T01', 'explicit': False},
                {'id': 'd', 'period': 'T01', 'explicit': False}]
        features = [{'id': i, 'description': i, 'source': 'stated', 'refs': r}
                    for i, r in [('quoted', ['q', 's']), ('setup', ['s']), ('setup-and-deduced', ['s', 'd']),
                                 ('foreign', ['r9'])]]
        out = _check_enrich('Issen', {'features': features, 'variants': [], 'conflicts': []}, refs,
                            {'T01': 0}, 'T01', 'T01')
        self.assertEqual([f['source'] for f in out['features']], ['stated', 'inferred', 'inferred', 'inferred'])

    def test_an_alias_two_entities_hold_names_neither(self):
        from lib.studio.archivist import _drop_shared_aliases, find_entity
        entities = {'reiden': {'key': 'reiden', 'ref_name': 'Reiden', 'aliases': ['Рэйден', 'я', 'Мать']},
                    'hideo': {'key': 'hideo', 'ref_name': 'Hideo', 'aliases': ['Хидео', 'Я', 'О-Сузу']},
                    'o-suzu': {'key': 'o-suzu', 'ref_name': 'O-Suzu', 'aliases': ['О-Сузу']},
                    'hitomi': {'key': 'hitomi', 'ref_name': 'Hitomi', 'aliases': ['мать', 'Хитоми']}}
        _drop_shared_aliases(entities)
        self.assertEqual({k: e['aliases'] for k, e in entities.items()},
                         {'reiden': ['Рэйден'], 'hideo': ['Хидео'], 'o-suzu': [], 'hitomi': ['Хитоми']})
        self.assertIsNone(find_entity({'entities': entities}, 'Я'))
        self.assertEqual(find_entity({'entities': entities}, 'O-Suzu')['key'], 'o-suzu')

    def test_the_setup_note_sees_every_name_of_the_cast(self):
        appendix = self.root / 'appendix'
        appendix.mkdir()
        (appendix / 's01e001.md').write_text('Кабинет: 4 × 5 × 3 м.', encoding='utf-8')
        CH_NAMES = 'Иван Петрович, Петрович, Ванька, Иван, сыщик, начальник надел пальто.'
        self.paths[0].write_text(CH_NAMES, encoding='utf-8')
        names = ['Иван Петрович', 'Петрович', 'Ванька', 'Иван', 'сыщик', 'начальник']

        class ManyNames(FakeLLM):
            def make_json(self, prompt, schema):
                if schema is BIBLE_CHUNK_SCHEMA and 'id="s01e001#001"' in prompt:
                    self.calls.append((schema, prompt))
                    return {'time': t('start'), 'entities': [
                        ent('Ivan-Petrov', 'Character', names, ('wardrobe', 'wears a coat', 'надел пальто'))]}
                return super().make_json(prompt, schema)
        _, _, llm = self.build(ManyNames())
        note = next(p for s, p in llm.calls if s is BIBLE_CHUNK_SCHEMA and '@setup' in p)
        self.assertIn(f"- Ivan-Petrov (Character): {', '.join(names)}\n", note)

    def test_bible_command_runs_under_its_own_system_prompt(self):
        from types import SimpleNamespace
        from lib.commands import setup
        args = SimpleNamespace(style=None, llm='debug', chapters=[str(p) for p in self.paths], force=False,
                               chunk_chars=archivist.CHUNK_CHARS, gleanings=0)
        project = SimpleNamespace(bible_dir=self.bible_dir, max_workers=1)
        with mock.patch.object(setup, 'load_project', return_value=(project, {'screenplay': 'FILM RULES'}, {})), \
                mock.patch.object(setup, '_make_llm', return_value=FakeLLM()) as make:
            setup.cmd_bible(args)
        self.assertEqual(make.call_args.kwargs['system_prompt'], archivist.SYSTEM_PROMPT)

    def test_markdown(self):
        self.build()
        md = (self.bible_dir / 'story_bible.md').read_text(encoding='utf-8')
        self.assertIn('⏪ `wall-safe`', md)
        self.assertIn('`brown-coat` | T02–T02', md)


class ConsumerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.project = Project()
        self.project.ref_dir, self.project.bible_dir, self.project.max_workers = root / 'refs', root / 'bible', 1
        self.project.ref_dir.mkdir()
        build_bible(write_chapters(root), FakeLLM(), self.project.bible_dir, workers=1)

    def test_detail_rooms_gets_features_and_warns_on_uncovered(self):
        from lib.studio.artist import detail_room_refs
        (self.project.ref_dir / 'detective-office-view-from-entrance.json').write_text(json.dumps({
            'name': 'Detective-Office-View-From-Entrance', 'type': 'Room',
            'visual_desc': 'Small office.', 'style_reference': ''}))
        llm = FakeLLM()
        with self.assertLogs('lib.studio.artist.room_detail', level='WARNING') as logs:
            detail_room_refs(CH['s01e001'], llm, self.project)
        self.assertTrue(any('without a named position: wall-safe' in m for m in logs.output))
        self.assertIn('[wall-safe]', next(p for s, p in llm.calls if s is ROOM_VOCABULARY_SCHEMA))



def returned_names(prompt):
    block = prompt.split('## RETURN EXACTLY THESE ENTRIES')[1].split('RULES')[0]
    return re.findall(r'^- (\S+) — ', block, re.M)


class CastLLM:
    """Writes an entry for every requested name, except names in `skip_once` on their first request;
    adds one entry nobody asked for."""

    def __init__(self, skip_once=()):
        self.prompts, self.skip = [], set(skip_once)

    def make_json(self, prompt, schema):
        assert schema is CHARACTER_SCHEMA
        self.prompts.append(prompt)
        out = []
        for name in returned_names(prompt):
            if name in self.skip:
                self.skip.discard(name)
                continue
            out.append({'name': name, 'type': 'Whatever', 'visual_desc': f'desc of {name}',
                        'video_visual_desc': 'v', 'logline_subject_info': '', 'style_reference': 'ignored'})
        return out + [{'name': 'Bogus-Extra', 'visual_desc': 'x'}]


class BibleCastingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.project = Project()
        self.project.ref_dir, self.project.bible_dir, self.project.max_workers = root / 'refs', root / 'bible', 1
        self.project.ref_dir.mkdir()
        self.bible, _ = build_bible(write_chapters(root), FakeLLM(), self.project.bible_dir, workers=1)

    def cast(self, chapter, llm=None, update=True):
        from lib.studio.bible_casting import cast_from_bible
        llm = llm or CastLLM()
        return cast_from_bible(self.bible, chapter, {}, llm, self.project, update=update), llm

    def ref(self, name):
        return json.loads((self.project.ref_dir / f'{name.lower()}.json').read_text(encoding='utf-8'))

    def write_ref(self, ref_name, **data):
        (self.project.ref_dir / f'{ref_name.lower()}.json').write_text(json.dumps({'name': ref_name, **data}))

    def test_plan_views_and_variants_by_story_time(self):
        from lib.studio.bible_casting import plan
        office, ivan = self.bible['entities']['detective-office'], self.bible['entities']['ivan-petrov']
        self.assertEqual([s.name for s in plan(self.bible, office, None)],
                         [f'Detective-Office-{v}' for v, _ in _ROOM_VIEWS])
        week1 = plan(self.bible, ivan, chapter_window(self.bible, 's01e001'))
        self.assertEqual([s.name for s in week1], ['Ivan-Petrov'])
        week2 = plan(self.bible, ivan, chapter_window(self.bible, 's01e002'))
        self.assertEqual(week2[1].name, 'Ivan-Petrov-Brown-Coat')
        self.assertIn('outdoors (Week 2 – Week 2)', week2[1].context)

    def test_casting_reads_the_setting_and_its_era_over_the_bible(self):
        from lib.studio.bible_casting import cast_from_bible
        llm = CastLLM()
        cast_from_bible(self.bible, 's01e001', {'setting': '## Real-world anchor\n- **Analog**: Russia, 1990s'}, llm,
                        self.project)
        self.assertTrue(all('- **Analog**: Russia, 1990s' in p for p in llm.prompts))
        self.assertTrue(all('a bible error — leave it out and draw the era\'s own counterpart' in p
                            for p in llm.prompts))

    def test_prompts_pin_the_cast_spelling(self):
        _, llm = self.cast('s01e001')
        self.assertTrue(all('9. Names: write characters exactly as Ivan Petrov —' in p for p in llm.prompts))

    def test_chapter_refs_are_planned_retried_and_owned_by_code(self):
        summary, llm = self.cast('s01e001', CastLLM(skip_once={'Detective-Office-View-To-Entrance'}))
        self.assertEqual(len(summary['written']), 1 + len(_ROOM_VIEWS))  # Ivan + office views; no car in s01e001
        self.assertEqual(summary['failed'], [])
        self.assertEqual(len(llm.prompts), 3)          # one per entity + one retry for the skipped view
        self.assertEqual(returned_names(llm.prompts[-1]), ['Detective-Office-View-To-Entrance'])
        office_prompt = next(p for p in llm.prompts if 'Detective-Office-View-From-Entrance' in p)
        self.assertIn('[wall-safe]', office_prompt)
        self.assertIn('Он достал револьвер из сейфа', office_prompt)  # source excerpt
        vte = self.ref('Detective-Office-View-To-Entrance')
        self.assertEqual((vte['type'], vte['style_reference']), ('Room', 'Detective-Office-View-From-Entrance'))
        self.assertEqual((vte['bible_key'], vte['bible_view']), ('detective-office', 'View-To-Entrance'))
        self.assertEqual(self.ref('Detective-Office-View-From-Entrance')['style_reference'], '')
        self.assertEqual(self.ref('Ivan-Petrov')['logline_subject_info'], 'Ivan-Petrov')  # role fallback
        self.assertFalse((self.project.ref_dir / 'bogus-extra.json').exists())

    def test_unchanged_bible_makes_no_calls(self):
        self.cast('s01e001')
        summary, llm = self.cast('s01e001')
        self.assertEqual((llm.prompts, summary['current']), ([], 1 + len(_ROOM_VIEWS)))

    def test_changed_entity_is_rewritten_and_loses_derived_data(self):
        self.cast('s01e001')
        vfe = 'Detective-Office-View-From-Entrance'
        self.write_ref(vfe, **{**self.ref(vfe), 'anchor_points': [1], 'details_applied': True})
        (self.project.ref_dir / f'{vfe.lower()}.png').write_bytes(b'png')
        self.bible['entities']['detective-office']['visual_desc'] = 'Office after the search.'
        summary, llm = self.cast('s01e001')
        self.assertEqual(len(llm.prompts), 1)  # the office only; Ivan is current
        self.assertIn('Office after the search.', llm.prompts[0])
        ref = self.ref(vfe)
        self.assertTrue(ref['needs_regenerate'])
        self.assertNotIn('anchor_points', ref)
        self.assertNotIn('details_applied', ref)

    def test_variant_ref_links_to_base(self):
        self.cast('s01e002')
        coat = self.ref('Ivan-Petrov-Brown-Coat')
        self.assertEqual((coat['character_ref'], coat['style_reference'], coat['bible_variant']),
                         ('Ivan-Petrov', 'Ivan-Petrov', 'brown-coat'))
        self.assertEqual(self.ref('Ivan-Petrov')['variations'], ['Ivan-Petrov-Brown-Coat'])

    def test_base_drops_stale_bible_variations_and_keeps_hand_made_ones(self):
        self.write_ref('Ivan-Petrov-Tux', type='Character', character_ref='Ivan-Petrov')  # hand-made
        self.write_ref('Ivan-Petrov-Old-Look', type='Character', bible_key='ivan-petrov', bible_variant='old-look')
        self.write_ref('Ivan-Petrov', type='Character', bible_key='ivan-petrov',
                       variations=['Ivan-Petrov-Tux', 'Ivan-Petrov-Old-Look', 'Ivan-Petrov-Deleted'])
        self.cast('s01e002')
        self.assertEqual(self.ref('Ivan-Petrov')['variations'], ['Ivan-Petrov-Tux', 'Ivan-Petrov-Brown-Coat'])

    def test_pre_bible_ref_is_adopted_under_its_own_name(self):
        self.write_ref('Ivan-Petrovich', type='Character', visual_desc='old', anchor_points=[1])  # alias name
        summary, _ = self.cast('s01e001')
        self.assertIn('Ivan-Petrovich', summary['written'])
        self.assertFalse((self.project.ref_dir / 'ivan-petrov.json').exists())
        self.assertEqual(self.ref('Ivan-Petrovich')['bible_key'], 'ivan-petrov')

    def test_no_update_links_without_rewriting(self):
        self.write_ref('Ivan-Petrovich', type='Character', visual_desc='old', anchor_points=[1])
        summary, llm = self.cast('s01e001', update=False)
        self.assertEqual(summary['linked'], ['Ivan-Petrovich'])
        ref = self.ref('Ivan-Petrovich')
        self.assertEqual((ref['visual_desc'], ref['anchor_points'], ref['bible_key']), ('old', [1], 'ivan-petrov'))
        self.assertNotIn('bible_hash', ref)
        self.assertTrue(all('Ivan-Petrovich' not in returned_names(p) for p in llm.prompts))

    def test_name_owned_by_another_entity_is_not_overwritten(self):
        self.write_ref('Ivan-Petrov', type='Character', visual_desc='someone else', bible_key='other-ivan')
        summary, llm = self.cast('s01e001')
        self.assertIn('Ivan-Petrov', summary['failed'])
        self.assertEqual(self.ref('Ivan-Petrov')['visual_desc'], 'someone else')
        self.assertTrue(all('Ivan-Petrov' not in returned_names(p) for p in llm.prompts))

    def test_orphan_is_reported(self):
        self.write_ref('Gone-Man', type='Character', visual_desc='x', bible_key='gone-man')
        summary, _ = self.cast('s01e001')
        self.assertEqual(summary['orphans'], ['Gone-Man'])


if __name__ == '__main__':
    unittest.main()


class CastReplyShapeTests(unittest.TestCase):
    """A weak model's reply for one ref: a bare object, a wrapped array, a renamed entry."""

    def setUp(self):
        from lib.studio.bible_casting import Slot
        self.lotus = Slot(key='giant-lotus', variant='', view='', name='Giant-Lotus')

    def match(self, reply, todo=None):
        from lib.studio.bible_casting import _match
        return _match(reply, todo or [self.lotus])

    def test_bare_object_is_one_entry(self):
        self.assertIn('Giant-Lotus', self.match({'name': 'Giant-Lotus', 'visual_desc': 'x'}))

    def test_wrapped_array_is_unwrapped(self):
        self.assertIn('Giant-Lotus', self.match({'entries': [{'name': 'giant lotus'}]}))

    def test_lone_slot_takes_lone_entry_whatever_its_name(self):
        self.assertEqual(self.match([{'name': 'Amida-Lotus', 'visual_desc': 'x'}])['Giant-Lotus']['visual_desc'], 'x')

    def test_several_slots_match_by_name_only(self):
        from dataclasses import replace
        other = replace(self.lotus, name='Giant-Lotus-Wilted')
        self.assertEqual(self.match([{'name': 'Something'}], [self.lotus, other]), {})

    def test_parse_json_keeps_a_one_item_array_after_preamble(self):
        from lib.llm.base import parse_json
        self.assertEqual(parse_json('Here: [{"name": "a"}] done'), [{'name': 'a'}])
        self.assertEqual(parse_json('Here: {"a": [1]} done'), {'a': [1]})


class LatinNameTests(unittest.TestCase):
    def test_romanizes_cyrillic_words_keeps_latin_ones(self):
        from lib.studio.archivist import latin_name, ref_key
        for src, out in [('Торюмон-Рэйден', 'Toryumon-Reyden'), ('Торюмон-House-Garden', 'Toryumon-House-Garden'),
                         ('Хонган-дзи-Ruins', 'Hongan-Dzi-Ruins'), ('NKVD-Office', 'NKVD-Office'),
                         ('Ёсида Сёин', 'Yosida-Syoin'), ('Kennō', 'Kenno'), ('Рёма-Ōsaka', 'Ryoma-Osaka')]:
            self.assertEqual(latin_name(src), out)
            self.assertEqual(ref_key(out), ref_key(src))

    def test_accented_latin_folds_instead_of_dropping(self):
        from lib.studio.archivist import ref_key
        self.assertEqual(ref_key('Kennō'), 'kenno')
        self.assertEqual(ref_key('Café-Müller'), 'cafe-muller')
        self.assertEqual(ref_key('Йошида'), 'yoshida')
