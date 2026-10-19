"""
Serializers for Quiz app.
"""
from rest_framework import serializers
from .models import (
    Question, QuestionOption, Quiz, QuizQuestion,
    MockTest, QuizAttempt, MockTestAttempt, Answer, QuestionReport
)


class QuestionOptionSerializer(serializers.ModelSerializer):
    """Serializer for question options."""
    
    class Meta:
        model = QuestionOption
        fields = ['id', 'option_text', 'option_image', 'order']


class QuestionSerializer(serializers.ModelSerializer):
    """Serializer for questions."""
    options = QuestionOptionSerializer(many=True, read_only=True)
    topic_name = serializers.SerializerMethodField()
    subject_name = serializers.SerializerMethodField()

    def get_topic_name(self, obj):
        return obj.topic.name if obj and getattr(obj, 'topic', None) else None

    def get_subject_name(self, obj):
        return obj.subject.name if obj and getattr(obj, 'subject', None) else None

    class Meta:
        model = Question
        fields = [
            'id', 'question_text', 'question_html', 'question_image',
            'question_type', 'difficulty', 'topic', 'topic_name',
            'subject', 'subject_name', 'marks', 'negative_marks',
            'options', 'source', 'year', 'tags'
        ]


class QuestionWithAnswerSerializer(QuestionSerializer):
    """Serializer that includes correct answer and explanation."""
    options = serializers.SerializerMethodField()
    
    class Meta(QuestionSerializer.Meta):
        fields = QuestionSerializer.Meta.fields + [
            'correct_answer', 'explanation', 'explanation_image',
            'numerical_answer', 'accuracy_rate'
        ]
    
    def get_options(self, obj):
        options = obj.options.all() if obj else []
        result = []
        for opt in options:
            try:
                img_url = None
                if getattr(opt, 'option_image', None):
                    img_url = getattr(opt.option_image, 'url', None)
            except Exception:
                img_url = None
            result.append({
                'id': str(opt.id),
                'option_text': opt.option_text,
                'option_image': img_url,
                'order': opt.order,
                'is_correct': opt.is_correct
            })
        return result


class QuizSerializer(serializers.ModelSerializer):
    """Serializer for quiz listings."""
    questions_count = serializers.ReadOnlyField()
    course_name = serializers.CharField(source='course.name', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    topic_name = serializers.CharField(source='topic.name', read_only=True)
    user_attempt_info = serializers.SerializerMethodField()
    
    class Meta:
        model = Quiz
        fields = [
            'id', 'title', 'description', 'quiz_type', 'status',
            'course', 'course_name', 'subject', 'subject_name',
            'topic', 'topic_name', 'questions_count',
            'duration_minutes', 'total_marks', 'is_free',
            'is_daily_challenge', 'challenge_date',
            'total_attempts', 'average_score', 'created_at',
            'user_attempt_info'
        ]
    
    def get_user_attempt_info(self, obj):
        """Get user's attempt info for this quiz."""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        
        try:
            profile = request.user.profile
            attempts = QuizAttempt.objects.filter(
                student=profile,
                quiz=obj,
                status='completed'
            ).order_by('-completed_at')
            
            if not attempts.exists():
                return None
            
            best_attempt = attempts.order_by('-percentage').first()
            latest_attempt = attempts.first()
            
            return {
                'attempted': True,
                'attempts_count': attempts.count(),
                'best_score': float(best_attempt.percentage) if best_attempt else 0,
                'best_attempt_id': str(best_attempt.id) if best_attempt else None,
                'latest_attempt_id': str(latest_attempt.id) if latest_attempt else None,
                'latest_score': float(latest_attempt.percentage) if latest_attempt else 0,
                'latest_date': latest_attempt.completed_at.isoformat() if latest_attempt else None,
            }
        except Exception:
            return None


class QuizDetailSerializer(QuizSerializer):
    """Detailed serializer with questions."""
    questions = QuestionSerializer(many=True, read_only=True)
    marking_scheme = serializers.SerializerMethodField()
    
    class Meta(QuizSerializer.Meta):
        fields = QuizSerializer.Meta.fields + [
            'questions', 'shuffle_questions', 'shuffle_options',
            'show_answer_after_each', 'allow_skip', 'passing_marks',
            'marking_scheme'
        ]
    
    def get_marking_scheme(self, obj):
        """Return marking scheme from question data."""
        questions = obj.questions.all()
        if not questions.exists():
            return None
        # Get the most common marks/negative_marks from questions
        first_q = questions.first()
        total = sum(q.marks for q in questions)
        return {
            'marks_per_question': float(first_q.marks) if first_q else 1,
            'negative_marks_per_question': float(first_q.negative_marks) if first_q else 0,
            'total_marks': float(total),
            'total_questions': questions.count(),
        }


class MockTestSerializer(serializers.ModelSerializer):
    """Serializer for mock test listings."""
    course_name = serializers.CharField(source='course.name', read_only=True)
    questions_count = serializers.SerializerMethodField()
    user_attempt_info = serializers.SerializerMethodField()
    
    class Meta:
        model = MockTest
        fields = [
            'id', 'title', 'description', 'course', 'course_name',
            'duration_minutes', 'total_marks', 'negative_marking',
            'status', 'is_free', 'sections', 'questions_count', 'max_attempts',
            'total_attempts', 'average_score', 'highest_score',
            'available_from', 'available_until', 'created_at',
            'user_attempt_info'
        ]
    
    def get_questions_count(self, obj):
        # Count both legacy bank questions and rich inline items so the card
        # reflects the true question count for either mock-test style.
        return obj.questions.count() + obj.items.count()
    
    def get_user_attempt_info(self, obj):
        """Get user's attempt info for this mock test."""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        
        try:
            profile = request.user.profile
            # Attempts that count toward the per-test limit.
            finished = MockTestAttempt.objects.filter(
                student=profile, mock_test=obj,
                status__in=['completed', 'timed_out'],
            ).order_by('-completed_at')
            active = MockTestAttempt.objects.filter(
                student=profile, mock_test=obj, status='in_progress',
            ).order_by('-started_at').first()

            attempts_used = finished.count()
            max_attempts = obj.max_attempts or 1
            # A resume doesn't consume a new attempt; a fresh start is allowed
            # only while used attempts are below the cap.
            can_reattempt = attempts_used < max_attempts

            completed = finished.filter(status='completed')

            # A score should only surface once an attempt is fully graded AND its
            # results are visible — otherwise a partial (auto-only) percentage
            # would misrepresent an attempt still awaiting manual grading.
            results_visible = (obj.result_visibility == 'immediate') or obj.results_released
            def scorable(a):
                return a.grading_status in ('auto_graded', 'graded') and results_visible

            scored = [a for a in completed if scorable(a)]
            best_attempt = max(scored, key=lambda a: a.percentage) if scored else None
            latest_completed = completed.first()  # ordered by -completed_at
            latest_attempt = finished.first()
            # Review target: prefer the best scored attempt, else the latest one.
            review_attempt = best_attempt or latest_completed or latest_attempt
            has_score = best_attempt is not None

            if not finished.exists() and not active:
                return {
                    'attempted': False,
                    'attempts_used': 0,
                    'max_attempts': max_attempts,
                    'can_reattempt': can_reattempt,
                    'active_attempt_id': None,
                }

            return {
                'attempted': completed.exists(),
                'attempts_count': attempts_used,
                'attempts_used': attempts_used,
                'max_attempts': max_attempts,
                'can_reattempt': can_reattempt,
                'active_attempt_id': str(active.id) if active else None,
                # Score fields are populated only when a fully-graded, visible
                # result exists. `results_pending` lets the UI show an
                # "awaiting grading" state instead of a misleading percentage.
                'has_score': has_score,
                'results_pending': completed.exists() and not has_score,
                'best_score': float(best_attempt.percentage) if has_score else None,
                'best_attempt_id': str(review_attempt.id) if review_attempt else None,
                'latest_attempt_id': str(latest_attempt.id) if latest_attempt else None,
                'latest_score': float(latest_completed.percentage) if has_score and latest_completed else None,
                'latest_date': latest_attempt.completed_at.isoformat() if latest_attempt and latest_attempt.completed_at else None,
                'rank': best_attempt.rank if best_attempt else None,
                'percentile': float(best_attempt.percentile) if best_attempt and best_attempt.percentile else None,
            }
        except Exception:
            return None


class MockTestDetailSerializer(MockTestSerializer):
    """Detailed mock test serializer."""
    questions = QuestionSerializer(many=True, read_only=True)
    marking_scheme = serializers.SerializerMethodField()
    
    class Meta(MockTestSerializer.Meta):
        fields = MockTestSerializer.Meta.fields + ['questions', 'marking_scheme']
    
    def get_marking_scheme(self, obj):
        """Return marking scheme from course and question data."""
        from .models import MockTestQuestion
        mtqs = MockTestQuestion.objects.filter(mock_test=obj).select_related('question')
        if not mtqs.exists():
            return None
        
        # Calculate effective totals using overrides
        total_marks = sum(float(mtq.effective_marks) for mtq in mtqs)
        
        # Get most common marks scheme (for display purposes)
        first_mtq = mtqs.first()
        marks = float(first_mtq.effective_marks)
        negative = float(first_mtq.effective_negative_marks)
        
        return {
            'marks_per_question': marks,
            'negative_marks_per_question': negative,
            'total_marks': total_marks,
            'total_questions': mtqs.count(),
            'negative_marking': obj.negative_marking,
            'duration_minutes': obj.duration_minutes,
        }


class PreviousYearPaperSerializer(MockTestSerializer):
    """Serializer for Previous Year Paper listings."""
    
    class Meta(MockTestSerializer.Meta):
        fields = MockTestSerializer.Meta.fields + [
            'is_pyp', 'pyp_year', 'pyp_shift', 'pyp_session', 'pyp_date'
        ]


class PreviousYearPaperDetailSerializer(MockTestDetailSerializer):
    """Detailed PYP serializer with questions."""
    
    class Meta(MockTestDetailSerializer.Meta):
        fields = MockTestDetailSerializer.Meta.fields + [
            'is_pyp', 'pyp_year', 'pyp_shift', 'pyp_session', 'pyp_date'
        ]


class AnswerSerializer(serializers.ModelSerializer):
    """Serializer for answers."""
    question_data = serializers.SerializerMethodField()

    def get_question_data(self, obj):
        question = getattr(obj, 'question', None)
        if not question:
            return None
        try:
            return QuestionWithAnswerSerializer(question, context=self.context).data
        except Exception:
            return {'id': str(question.id), 'question_text': getattr(question, 'question_text', '')}

    class Meta:
        model = Answer
        fields = [
            'id', 'question', 'question_data', 'selected_option',
            'answer_text', 'numerical_answer', 'is_correct',
            'marks_obtained', 'time_taken_seconds', 'is_marked_for_review'
        ]
        read_only_fields = ['id', 'is_correct', 'marks_obtained']


class AnswerSubmitSerializer(serializers.Serializer):
    """Serializer for submitting an answer."""
    question_id = serializers.UUIDField()
    selected_option = serializers.CharField(required=False, allow_blank=True)
    answer_text = serializers.CharField(required=False, allow_blank=True)
    numerical_answer = serializers.DecimalField(
        max_digits=20, decimal_places=10, required=False, allow_null=True
    )
    time_taken_seconds = serializers.IntegerField(default=0)
    is_marked_for_review = serializers.BooleanField(default=False)


class QuizAttemptSummarySerializer(serializers.ModelSerializer):
    """Summary serializer for quiz attempts (without answers)."""
    quiz_title = serializers.CharField(source='quiz.title', read_only=True)
    
    class Meta:
        model = QuizAttempt
        fields = [
            'id', 'quiz', 'quiz_title', 'started_at', 'completed_at',
            'time_taken_seconds', 'status', 'total_questions',
            'attempted_questions', 'correct_answers', 'wrong_answers',
            'skipped_questions', 'marks_obtained', 'total_marks',
            'percentage', 'xp_earned', 'proctoring_violations',
            'tab_switch_count', 'fullscreen_exit_count',
            'restricted_shortcut_count', 'last_proctoring_event_at'
        ]


class QuizAttemptSerializer(serializers.ModelSerializer):
    """Serializer for quiz attempts with answers."""
    quiz_title = serializers.CharField(source='quiz.title', read_only=True)
    answers = AnswerSerializer(many=True, read_only=True)
    
    class Meta:
        model = QuizAttempt
        fields = [
            'id', 'quiz', 'quiz_title', 'started_at', 'completed_at',
            'time_taken_seconds', 'status', 'total_questions',
            'attempted_questions', 'correct_answers', 'wrong_answers',
            'skipped_questions', 'marks_obtained', 'total_marks',
            'percentage', 'xp_earned', 'proctoring_violations',
            'tab_switch_count', 'fullscreen_exit_count',
            'restricted_shortcut_count', 'last_proctoring_event_at', 'answers'
        ]
        read_only_fields = [
            'id', 'started_at', 'total_questions', 'attempted_questions',
            'correct_answers', 'wrong_answers', 'skipped_questions',
            'marks_obtained', 'total_marks', 'percentage', 'xp_earned',
            'proctoring_violations', 'tab_switch_count',
            'fullscreen_exit_count', 'restricted_shortcut_count',
            'last_proctoring_event_at'
        ]


class MockTestAttemptSummarySerializer(serializers.ModelSerializer):
    """Summary serializer for mock test attempts (without answers)."""
    mock_test_title = serializers.CharField(source='mock_test.title', read_only=True)
    total_marks = serializers.SerializerMethodField()
    
    class Meta:
        model = MockTestAttempt
        fields = [
            'id', 'mock_test', 'mock_test_title', 'started_at',
            'completed_at', 'time_taken_seconds', 'status',
            'total_questions', 'attempted_questions', 'correct_answers',
            'wrong_answers', 'marks_obtained', 'total_marks', 'percentage',
            'section_results', 'rank', 'percentile', 'xp_earned'
        ]
    
    def get_total_marks(self, obj):
        return float(obj.mock_test.total_marks)


class MockTestAttemptSerializer(serializers.ModelSerializer):
    """Serializer for mock test attempts with answers."""
    mock_test_title = serializers.CharField(source='mock_test.title', read_only=True)
    answers = AnswerSerializer(many=True, read_only=True)
    total_marks = serializers.SerializerMethodField()
    
    class Meta:
        model = MockTestAttempt
        fields = [
            'id', 'mock_test', 'mock_test_title', 'started_at',
            'completed_at', 'time_taken_seconds', 'status',
            'total_questions', 'attempted_questions', 'correct_answers',
            'wrong_answers', 'marks_obtained', 'total_marks', 'percentage',
            'section_results', 'rank', 'percentile', 'xp_earned', 'answers'
        ]
    
    def get_total_marks(self, obj):
        return float(obj.mock_test.total_marks)


class QuizStartSerializer(serializers.Serializer):
    """Serializer for starting a quiz."""
    quiz_id = serializers.UUIDField()


class QuizSubmitSerializer(serializers.Serializer):
    """Serializer for submitting a complete quiz."""
    answers = AnswerSubmitSerializer(many=True)
    time_taken_seconds = serializers.IntegerField()


class QuizAttemptReviewSerializer(serializers.ModelSerializer):
    """
    Serializer for detailed quiz attempt review.
    Includes ALL questions (answered and unanswered).
    """
    quiz_title = serializers.CharField(source='quiz.title', read_only=True)
    topic = serializers.CharField(source='quiz.topic_id', read_only=True)
    all_questions = serializers.SerializerMethodField()
    
    class Meta:
        model = QuizAttempt
        fields = [
            'id', 'quiz', 'quiz_title', 'started_at', 'completed_at',
            'time_taken_seconds', 'status', 'total_questions',
            'attempted_questions', 'correct_answers', 'wrong_answers',
            'skipped_questions', 'marks_obtained', 'total_marks',
            'percentage', 'xp_earned', 'all_questions', 'topic'
        ]
    
    def get_all_questions(self, obj):
        """Get all questions with user's answers (including unanswered)."""
        questions = obj.quiz.questions.all().order_by('id')
        answers_map = {str(a.question_id): a for a in obj.answers.all()}
        
        result = []
        for idx, question in enumerate(questions):
            q_id = str(question.id)
            answer = answers_map.get(q_id)
            
            # Serialize question with answer info
            question_data = QuestionWithAnswerSerializer(question).data
            
            result.append({
                'question_number': idx + 1,
                'question': question_data,
                'user_answer': {
                    'selected_option': answer.selected_option if answer else None,
                    'answer_text': answer.answer_text if answer else None,
                    'numerical_answer': str(answer.numerical_answer) if answer and answer.numerical_answer else None,
                    'is_correct': answer.is_correct if answer else None,
                    'marks_obtained': float(answer.marks_obtained) if answer else 0,
                    'time_taken_seconds': answer.time_taken_seconds if answer else 0,
                    'is_marked_for_review': answer.is_marked_for_review if answer else False,
                } if answer else None,
                'status': 'correct' if (answer and answer.is_correct) else ('wrong' if answer else 'skipped')
            })
        
        return result


class MockTestAttemptReviewSerializer(serializers.ModelSerializer):
    """
    Serializer for detailed mock test attempt review.
    Includes ALL questions (answered and unanswered).
    """
    mock_test_title = serializers.CharField(source='mock_test.title', read_only=True)
    all_questions = serializers.SerializerMethodField()
    total_marks = serializers.SerializerMethodField()
    
    class Meta:
        model = MockTestAttempt
        fields = [
            'id', 'mock_test', 'mock_test_title', 'started_at',
            'completed_at', 'time_taken_seconds', 'status',
            'total_questions', 'attempted_questions', 'correct_answers',
            'wrong_answers', 'marks_obtained', 'total_marks', 'percentage',
            'section_results', 'rank', 'percentile', 'xp_earned',
            'all_questions'
        ]
    
    def get_total_marks(self, obj):
        return float(obj.mock_test.total_marks)
    
    def get_all_questions(self, obj):
        """Get all questions with user's answers (including unanswered)."""
        questions = obj.mock_test.questions.all().order_by('id')
        answers_map = {str(a.question_id): a for a in obj.answers.all()}
        
        result = []
        for idx, question in enumerate(questions):
            q_id = str(question.id)
            answer = answers_map.get(q_id)
            
            # Serialize question with answer info
            question_data = QuestionWithAnswerSerializer(question).data
            
            result.append({
                'question_number': idx + 1,
                'question': question_data,
                'user_answer': {
                    'selected_option': answer.selected_option if answer else None,
                    'answer_text': answer.answer_text if answer else None,
                    'numerical_answer': str(answer.numerical_answer) if answer and answer.numerical_answer else None,
                    'is_correct': answer.is_correct if answer else None,
                    'marks_obtained': float(answer.marks_obtained) if answer else 0,
                    'time_taken_seconds': answer.time_taken_seconds if answer else 0,
                    'is_marked_for_review': answer.is_marked_for_review if answer else False,
                } if answer else None,
                'status': 'correct' if (answer and answer.is_correct) else ('wrong' if answer else 'skipped')
            })
        
        return result


class QuestionReportSerializer(serializers.ModelSerializer):
    """Serializer for question reports."""
    reported_by_name = serializers.CharField(source='reported_by.user.full_name', read_only=True)
    question_text = serializers.CharField(source='question.question_text', read_only=True)
    
    class Meta:
        model = QuestionReport
        fields = [
            'id', 'question', 'question_text', 'reported_by', 'reported_by_name',
            'report_type', 'description', 'status', 'admin_response',
            'created_at', 'resolved_at'
        ]
        read_only_fields = ['id', 'reported_by', 'status', 'admin_response', 'resolved_at']


class QuestionReportCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating question reports."""
    
    class Meta:
        model = QuestionReport
        fields = ['question', 'report_type', 'description']
    
    def create(self, validated_data):
        validated_data['reported_by'] = self.context['request'].user.profile
        return super().create(validated_data)
