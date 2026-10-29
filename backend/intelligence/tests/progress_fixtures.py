"""Shared fixtures for the My Progress tests: Part A's tenant, staff and
students, plus a small syllabus tree on ``subject`` and a second subject
(``optics``) without a tree."""
import uuid
from datetime import timedelta

from django.utils import timezone

from exams.models import Subject
from intelligence.models import (
    Concept, ConceptLink, LearnerConceptState, LearningEvent, SyllabusNode,
)
from intelligence.tests.visibility_fixtures import ALL_ON, VisibilityTestCase

PROGRESS_ON = {**ALL_ON, 'my_progress': True}


class ProgressTestCase(VisibilityTestCase):
    features = PROGRESS_ON

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.concepts = {}
        cls.mechanics = cls.node('mechanics', 'Mechanics', 'sub_subject')
        cls.kinematics = cls.node('kinematics', 'Kinematics', 'topic', cls.mechanics, weightage=0.6)
        cls.dynamics = cls.node('dynamics', 'Dynamics', 'topic', cls.mechanics, weightage=0.4)
        cls.velocity = cls.node('velocity', 'Velocity', 'subtopic', cls.kinematics)
        cls.projectile = cls.node('projectile', 'Projectile motion', 'subtopic', cls.kinematics)
        cls.relative = cls.node('relative', 'Relative motion', 'subtopic', cls.kinematics)
        cls.friction = cls.node('friction', 'Friction', 'subtopic', cls.dynamics)
        cls.optics = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Optics', code='vis-optics', order=1,
        )

    @classmethod
    def concept(cls, name, subject=None):
        concept = Concept.objects.create(
            tenant=cls.tenant, subject=subject or cls.subject, name=name.title(),
            slug=f'progress-{name}',
        )
        cls.concepts[name] = concept
        return concept

    @classmethod
    def node(cls, key, name, level, parent=None, *, weightage=0.0, status='active',
             in_syllabus=True, order=0):
        return SyllabusNode.objects.create(
            tenant=cls.tenant, subject=cls.subject, parent=parent, level=level,
            key=f'phy.{key}', name=name, weightage=weightage, status=status,
            in_syllabus=in_syllabus, order=order,
            concept=cls.concept(key) if level == 'subtopic' else None,
        )

    def set_state(self, concept, mastery, evidence, student=None):
        return LearnerConceptState.objects.create(
            tenant=self.tenant, student=student or self.student, concept=concept,
            mastery=mastery, evidence_count=max(1, round(evidence)),
            effective_evidence=evidence, computed_at=timezone.now(),
        )

    def hand_states(self, student=None):
        """The Task 3 fixture numbers: velocity 0.9/6, projectile 0.3/2,
        friction 0.4/4, relative motion untouched."""
        self.set_state(self.concepts['velocity'], 0.9, 6.0, student)
        self.set_state(self.concepts['projectile'], 0.3, 2.0, student)
        self.set_state(self.concepts['friction'], 0.4, 4.0, student)

    def link(self, question, concept):
        return ConceptLink.objects.create(
            tenant=self.tenant, concept=concept, question=question, source='generator',
        )

    def event(self, question, *, score, days_ago=0, attempt=None, student=None,
              source='quiz_answer', now=None):
        occurred = (now or timezone.now()) - timedelta(days=days_ago)
        return LearningEvent.objects.create(
            tenant=self.tenant, student=student or self.student, source_type=source,
            question=question, attempt_kind='quiz' if attempt else '',
            attempt_id=attempt.id if attempt else None, subject=question.subject,
            occurred_at=occurred, is_correct=score >= 1.0, score_fraction=score,
            dedup_key=f'{source}:{uuid.uuid4()}:0',
        )
