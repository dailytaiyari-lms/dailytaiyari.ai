"""Item tagging: link replacement, difficulty guard, staleness, draft round-trip."""
from django.test import TestCase

from core.models import Tenant
from exams.models import Course, Subject, Topic
from intelligence.models import Concept, ConceptLink
from intelligence.services.itemtags import mark_stale_if_changed, set_item_tags
from mockgen.apply import draft_from_mock_test
from quiz.models import MockTest, MockTestItem


class ItemTagTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name='Tag Academy', is_active=True)
        cls.course = Course.objects.create(
            tenant=cls.tenant, name='Physics', code='physics', course_type='competitive',
        )
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Mechanics', code='mechanics',
        )
        cls.topic = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Kinematics', code='kinematics',
        )
        cls.mock_test = MockTest.objects.create(
            tenant=cls.tenant, course=cls.course, title='Paper', duration_minutes=60,
            total_marks=10,
        )

    def make_item(self, **overrides):
        defaults = dict(
            tenant=self.tenant, mock_test=self.mock_test, item_type='mcq',
            question_text='A projectile is launched at 45°. Which vector stays constant?',
            options=[
                {'text': 'Velocity', 'is_correct': False},
                {'text': 'Horizontal velocity', 'is_correct': True},
            ],
            marks=4,
        )
        defaults.update(overrides)
        return MockTestItem.objects.create(**defaults)

    def test_set_item_tags_links_concepts_and_metadata(self):
        item = self.make_item()
        set_item_tags(
            item,
            concept_labels=['Projectile Motion', 'Vectors'],
            subject=self.subject, topic=self.topic, source='generator',
            difficulty='hard', cognitive_type='multi_concept',
            overwrite_difficulty=True,
        )
        item.refresh_from_db()
        self.assertEqual(item.difficulty, 'hard')
        self.assertEqual(item.cognitive_type, 'multi_concept')
        self.assertEqual(item.tagging_status, 'tagged')
        self.assertEqual(item.subject, self.subject)
        self.assertEqual(item.topic, self.topic)
        self.assertTrue(item.content_hash)

        links = list(item.concept_links.order_by('-is_primary'))
        self.assertEqual(len(links), 2)
        self.assertTrue(links[0].is_primary)
        self.assertEqual(links[0].weight, 1.0)
        self.assertEqual(links[0].concept.name, 'Projectile Motion')
        self.assertEqual(links[1].weight, 0.5)
        self.assertEqual(Concept.objects.count(), 2)

    def test_retag_replaces_own_links_but_keeps_manual_ones(self):
        item = self.make_item()
        manual_concept = Concept.objects.create(
            tenant=self.tenant, subject=self.subject, name='Teacher Concept',
            slug='teacher-concept', source='manual',
        )
        ConceptLink.objects.create(
            tenant=self.tenant, concept=manual_concept, mock_item=item,
            source='manual', is_primary=False, weight=1.0,
        )
        set_item_tags(item, concept_labels=['Projectile Motion'], subject=self.subject,
                      source='llm_tagger')
        set_item_tags(item, concept_labels=['Relative Motion'], subject=self.subject,
                      source='llm_tagger')
        sources = sorted(item.concept_links.values_list('source', flat=True))
        self.assertEqual(sources, ['llm_tagger', 'manual'])
        llm_link = item.concept_links.get(source='llm_tagger')
        self.assertEqual(llm_link.concept.name, 'Relative Motion')

    def test_tagger_never_overwrites_authored_difficulty(self):
        item = self.make_item(difficulty='easy')
        # Simulate an author-tagged item being re-tagged by the sweep.
        set_item_tags(item, concept_labels=['Vectors'], subject=self.subject,
                      source='generator', difficulty='easy', overwrite_difficulty=True)
        set_item_tags(item, concept_labels=['Vectors'], subject=self.subject,
                      source='llm_tagger', difficulty='hard')
        item.refresh_from_db()
        self.assertEqual(item.difficulty, 'easy')

    def test_mark_stale_on_content_change(self):
        item = self.make_item()
        set_item_tags(item, concept_labels=['Vectors'], subject=self.subject,
                      source='generator')
        self.assertFalse(mark_stale_if_changed(item))  # unchanged
        item.question_text = 'Completely different question?'
        item.save(update_fields=['question_text'])
        self.assertTrue(mark_stale_if_changed(item))
        item.refresh_from_db()
        self.assertEqual(item.tagging_status, 'stale')

    def test_draft_round_trip_preserves_metadata(self):
        item = self.make_item()
        set_item_tags(
            item, concept_labels=['Projectile Motion', 'Vectors'],
            subject=self.subject, source='generator',
            difficulty='hard', cognitive_type='multi_concept',
            overwrite_difficulty=True,
        )
        draft = draft_from_mock_test(self.mock_test)
        entry = draft['items'][0]
        self.assertEqual(entry['difficulty'], 'hard')
        self.assertEqual(entry['cognitive_type'], 'multi_concept')
        self.assertEqual(entry['concepts'][0], 'Projectile Motion')
        self.assertEqual(entry['concept'], 'Projectile Motion')
