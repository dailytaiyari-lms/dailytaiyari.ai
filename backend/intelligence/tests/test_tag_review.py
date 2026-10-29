"""Tag review actions (spec 2B §5.3)."""
from intelligence.models import ConceptLink, ItemSkillTag, ItemTagging, SyllabusNode, TagDefinition
from intelligence.services import syllabus, tag_review, tagging_sweep
from intelligence.services.tag_review import ReviewError
from intelligence.tests.syllabus_fixtures import SyllabusTestCase
from intelligence.tests.test_tagging_sweep import FakeCall, patched_tree, tag_entry


class ReviewTestCase(SyllabusTestCase):
    def setUp(self):
        super().setUp()
        self.item = self.question('A 2 kg block on a rough floor…')
        friction = syllabus.ensure_node_concept(self.friction)
        ConceptLink.objects.create(tenant=self.tenant, concept=friction, question=self.item,
                                   is_primary=True, source='llm_tagger')
        self.tagging = ItemTagging.objects.create(
            tenant=self.tenant, question=self.item, primary_node=self.friction,
            thinking_level='recall', confidence=0.4, review_status='needs_review',
            review_reasons=['low_confidence'], raw={'topic_key': self.laws_node.key},
        )
        ItemSkillTag.objects.create(
            tenant=self.tenant, question=self.item, role='core', source='llm_tagger',
            skill=TagDefinition.objects.get(kind='skill', key='free_body_diagram'))


class AcceptAndPayloadTests(ReviewTestCase):
    def test_row_payload(self):
        row = tag_review.row_payload(self.tagging)
        self.assertEqual(row['item_kind'], 'bank')
        self.assertEqual(row['primary']['name'], 'Friction')
        self.assertEqual(row['skills'][0]['key'], 'free_body_diagram')
        self.assertEqual(row['review_reasons'], ['low_confidence'])
        self.assertEqual(row['topic'], 'Laws of Motion')

    def test_accept_and_bulk_accept(self):
        tag_review.accept(self.tagging)
        self.tagging.refresh_from_db()
        self.assertEqual(self.tagging.review_status, 'reviewed')
        self.tagging.review_status = 'needs_review'
        self.tagging.save()
        self.assertEqual(tag_review.bulk_accept(ItemTagging.objects.all()), 1)

    def test_edit_choices(self):
        choices = tag_review.edit_choices(self.physics)
        laws = next(t for t in choices['topics'] if t['name'] == 'Laws of Motion')
        self.assertEqual([s['name'] for s in laws['subtopics']], ['Friction', "Newton's Laws"])
        self.assertIn('recall', [t['key'] for t in choices['thinking_levels']])
        self.assertIn('free_body_diagram', [s['key'] for s in choices['skills']])


class ManualEditTests(ReviewTestCase):
    def edit(self, **overrides):
        data = {
            'primary': str(self.newton.id), 'secondary': [str(self.friction.id)],
            'thinking_level': 'single_application',
            'skills': [{'key': 'formula_application', 'role': 'core', 'reason': 'F = ma'}],
            'special_format': '', 'difficulty_prior': 'hard', 'est_solve_seconds': 90,
        }
        data.update(overrides)
        return tag_review.save_manual(self.tagging, data)

    def test_edit_locks_tags_and_rewrites_links(self):
        self.edit()
        self.tagging.refresh_from_db()
        self.assertEqual((self.tagging.source, self.tagging.review_status), ('manual', 'reviewed'))
        self.assertEqual(self.tagging.primary_node_id, self.newton.id)
        links = ConceptLink.objects.filter(question=self.item)
        self.assertEqual({link.source for link in links}, {'manual'})
        self.assertEqual(links.get(is_primary=True).concept_id, self.newton.concept_id)
        skills = ItemSkillTag.objects.filter(question=self.item)
        self.assertEqual([(s.skill.key, s.source) for s in skills], [('formula_application', 'manual')])
        self.item.refresh_from_db()
        self.assertEqual(self.item.cognitive_type, 'application')

    def test_next_sweep_skips_a_manual_item(self):
        self.edit()
        call = FakeCall(tag={str(self.item.id): tag_entry()})
        with patched_tree():
            tagging_sweep.tag_v2_for_tenant(self.tenant, {self.physics.id}, call)
        self.tagging.refresh_from_db()
        self.assertEqual(self.tagging.primary_node_id, self.newton.id)
        self.assertEqual(call.calls, [])

    def test_validation(self):
        with self.assertRaises(ReviewError):
            self.edit(primary=str(self.laws_node.id))          # a topic, not a subtopic
        with self.assertRaises(ReviewError):
            self.edit(thinking_level='wizardry')
        with self.assertRaises(ReviewError):
            self.edit(skills=[{'key': 'nope', 'role': 'core'}])
        with self.assertRaises(ReviewError):
            self.edit(difficulty_prior='impossible')
        self.edit(est_solve_seconds=99999)
        self.tagging.refresh_from_db()
        self.assertEqual(self.tagging.est_solve_seconds, 1800)


class RetagAndAddToTreeTests(ReviewTestCase):
    def test_mark_for_retag_unlocks_and_stales(self):
        self.tagging.source = 'manual'
        self.tagging.save()
        tag_review.mark_for_retag(self.tagging)
        self.tagging.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.tagging.source, 'llm_tagger')
        self.assertEqual(self.item.tagging_status, 'stale')

    def test_mark_for_retag_hands_manual_links_and_skills_back(self):
        tag_review.save_manual(self.tagging, {
            'primary': str(self.newton.id), 'secondary': [str(self.friction.id)],
            'thinking_level': 'single_application',
            'skills': [{'key': 'formula_application', 'role': 'core', 'reason': 'F = ma'}],
            'special_format': '', 'difficulty_prior': 'hard', 'est_solve_seconds': 90,
        })
        tag_review.mark_for_retag(self.tagging)
        self.assertFalse(ConceptLink.objects.filter(question=self.item, source='manual').exists())
        self.assertFalse(ItemSkillTag.objects.filter(question=self.item, source='manual').exists())
        self.assertTrue(ConceptLink.objects.filter(question=self.item, source='llm_tagger').exists())

    def test_add_to_tree_creates_and_assigns(self):
        self.tagging.primary_node = None
        self.tagging.proposed_subtopic = 'Rolling friction'
        self.tagging.review_reasons = ['proposed_subtopic']
        self.tagging.save()
        node = tag_review.add_to_tree(self.tagging)
        self.assertEqual(node.parent_id, self.laws_node.id)
        self.assertEqual(node.name, 'Rolling friction')
        self.tagging.refresh_from_db()
        self.assertEqual((self.tagging.primary_node_id, self.tagging.source), (node.id, 'manual'))
        self.assertEqual(self.tagging.proposed_subtopic, '')

    def test_add_to_tree_reuses_a_same_named_subtopic(self):
        self.tagging.proposed_subtopic = 'friction'
        self.tagging.save()
        self.assertEqual(tag_review.add_to_tree(self.tagging).id, self.friction.id)

    def test_add_to_tree_needs_a_proposal(self):
        with self.assertRaises(ReviewError):
            tag_review.add_to_tree(self.tagging)
