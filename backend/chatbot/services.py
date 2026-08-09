"""AI doubt-solver services: prompt assembly, streaming, and session handling.

The actual model call is delegated to :mod:`chatbot.providers` via
:mod:`chatbot.resolver`, so the tenant's configured LLM (OpenAI, Azure, Gemini,
Claude, Groq/OpenRouter/Ollama open-source models…) is used transparently and
every call is metered for cost control.
"""
import json
import logging
import time

from . import resolver
from .course_context import course_context_for
from .models import AIUsageRecord
from .providers import AIProviderError, Usage
from .tenancy import tenant_of_student

logger = logging.getLogger(__name__)


BASE_SYSTEM_PROMPT = """You are an expert tutor inside an online learning platform, helping a student with the course they are enrolled in.

Your role is to:
1. Answer doubts clearly and concisely
2. Explain concepts step-by-step with clear reasoning
3. Provide examples and real-world analogies
4. Give tips for remembering formulas and concepts
5. Point out what is important for the student's exams
6. Suggest related topics to study next
7. Be encouraging, patient, and supportive
8. Create practice quizzes when asked

Guidelines:
- Use simple language that a student can understand
- For math/physics, show step-by-step solutions with numbered steps
- For chemistry, explain reactions with proper equations
- For biology, describe diagrams when helpful
- For formulas, explain what each variable/symbol means
- If a question is unclear, ask for clarification
- Use markdown formatting for better readability:
  - **Bold** for important terms
  - Numbered lists for steps
  - Bullet points for key points
  - > blockquotes for important notes/tips

**IMPORTANT - Math Formatting:**
- For mathematical equations, use LaTeX with dollar signs:
  - Inline math: $x = \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}$
  - Display math (own line): $$E = mc^2$$
- Always use $...$ for inline formulas and $$...$$ for block formulas

**IMPORTANT - Quiz Format:**
When a student asks for practice questions, a quiz, or says "quiz me", format the quiz EXACTLY like this:

Quiz Topic: [The concept the quiz covers, e.g. Newton's Laws of Motion]

Q1. [Question text here]
A) [Option A]
B) [Option B]
C) [Option C]
D) [Option D]
Answer: [Correct letter, e.g., B]
Topic: [The single concept this question tests, e.g. Free Body Diagrams]
Explanation: [Brief explanation of why this is correct]

Q2. [Next question...]
A) [Option A]
B) [Option B]
C) [Option C]
D) [Option D]
Answer: [Correct letter]
Topic: [Concept tested]
Explanation: [Brief explanation]

(Continue for all questions)

**IMPORTANT - Topic labels:**
The "Quiz Topic:" and per-question "Topic:" lines drive the student's mastery
tracking, so they must be genuinely informative:
- Name the actual syllabus concept being tested — never generic labels like
  "Practice Quiz", "Quiz", "General", "MCQ", "Test" or a bare subject name.
- Keep each label short (2-5 words) and in Title Case.
- Reuse the exact same wording for the same concept every time, so the student's
  progress on that concept accumulates across quizzes.
- Give every question its own "Topic:" line, placed after "Answer:" and before
  "Explanation:", even when all questions share the same concept.

Remember: you are helping a real student make progress. Be patient, helpful, and motivating. Every small concept matters!"""


# Appended whenever a course is selected, so the model knows the data below is
# real and how it is expected to use it.
COURSE_DATA_CLAUSE = """

**Using the student's own course data**
The context below is real data from this student's account — their progress, their
wrong answers, their submissions. Use it directly and specifically:
- When they ask about mistakes, quote the actual questions they got wrong, what they
  picked, and why the correct answer is right. Then name the underlying concept, since
  repeated mistakes usually share a root cause.
- When they ask about assignments, use the real titles, due dates and teacher feedback.
  Flag anything overdue or unsubmitted plainly, without nagging.
- When their code is failing, reason from the actual verdict and error output. "Wrong
  answer" on some cases usually means an edge case or off-by-one; a timeout usually means
  the approach is too slow; a compile error is a syntax or type problem. Suggest what to
  check, and ask to see their code when that would help more than guessing.
- Prefer naming one concrete next action over a generic list of options.
- Never invent a question, score, assignment, deadline or test case that is not listed.
  If the data does not cover something, say so plainly and offer what you can do instead.
- Refer back to what has already been discussed in this conversation instead of repeating
  yourself or asking again for something the student has already told you."""


NO_QUIZ_CLAUSE = (
    '\n\nQuiz generation is disabled on this platform. If the student asks for a quiz, '
    'politely explain that practice quizzes are available in the Practice Quiz section '
    'instead, and offer to explain the concept or give worked examples.'
)


def build_system_prompt(session, ai_settings=None):
    """Assemble the system prompt: base rules + tenant tweaks + course context."""
    prompt = BASE_SYSTEM_PROMPT

    if ai_settings is not None and not ai_settings.allow_quiz_generation:
        prompt += NO_QUIZ_CLAUSE

    context_parts = []
    if session.subject_id:
        context_parts.append(f'Subject: {session.subject.name}')
    if session.topic_id:
        context_parts.append(f'Topic: {session.topic.name}')
    if context_parts:
        prompt += (
            f"\n\nCurrent Context: {', '.join(context_parts)}. "
            'Focus your answers on this context.'
        )

    allow_course_context = ai_settings is None or ai_settings.allow_course_context
    if session.course_id and allow_course_context:
        try:
            course_block = course_context_for(session.student, session.course)
            if course_block:
                prompt += COURSE_DATA_CLAUSE + '\n\n' + course_block
        except Exception:  # noqa: BLE001 - context is an enhancement, never fatal
            logger.exception('Failed to build course context for session %s', session.id)

    if ai_settings is not None and ai_settings.custom_instructions:
        prompt += (
            '\n\n## Additional instructions from this institute\n'
            + ai_settings.custom_instructions.strip()
        )

    return prompt


HISTORY_TURNS = 30


def build_messages(session, history, ai_settings=None):
    """System prompt + recent conversation, in provider-neutral form.

    The window is what gives the assistant its memory of the exchange, so it
    can resolve "these quizzes", "that chapter" or "explain it again" against
    what was actually said earlier.
    """
    messages = [{'role': 'system', 'content': build_system_prompt(session, ai_settings)}]
    for msg in history[-HISTORY_TURNS:]:
        if msg['role'] in ('user', 'assistant') and msg['content']:
            messages.append({'role': msg['role'], 'content': msg['content']})
    return messages


UNAVAILABLE_TEMPLATE = """I can't answer right now.

{reason}

**In the meantime you can:**
- Review the topic's study notes and revision material
- Try a practice quiz on the topic
- Post your doubt in the Community for a peer or mentor to answer"""

PROVIDER_ERROR_REASON = (
    'The AI provider configured for your institute returned an error. '
    'Please try again in a moment.'
)


def unavailable_message(exc):
    return UNAVAILABLE_TEMPLATE.format(reason=exc.message)


def public_model_label(resolved):
    """What a student may be told about which model answered them.

    On the included allowance the real name is withheld: it is an operational
    choice we change and fail over between, and the tenant-facing panels go to
    some length not to name it — leaking it in a chat frame would undo that.
    The true model is still recorded on ``AIUsageRecord`` for our own billing.
    """
    if resolved.source == AIUsageRecord.SOURCE_PLATFORM:
        return 'included'
    return (resolved.model or '')[:50]


class ChatService:
    """Service for managing chat sessions and messages."""

    @staticmethod
    def create_session(student, topic=None, subject=None, title=None, course=None, tenant=None):
        """Create a new chat session."""
        from .models import ChatSession

        return ChatSession.objects.create(
            student=student,
            tenant=tenant,
            topic=topic,
            subject=subject,
            course=course,
            title=title or 'New Chat',
        )

    @staticmethod
    def add_message(session, role, content, **kwargs):
        """Add a message to a session."""
        from .models import ChatMessage

        message = ChatMessage.objects.create(
            session=session, tenant=session.tenant, role=role, content=content, **kwargs
        )

        session.message_count += 1
        if role == 'user' and (not session.title or session.title == 'New Chat'):
            session.title = content[:100]
        session.save()
        return message

    @staticmethod
    def get_session_history(session, limit=60):
        """The most recent ``limit`` messages, oldest first.

        Note the ordering: slicing ``order_by('created_at')[:limit]`` would take
        the *oldest* messages, so a long conversation would freeze its context
        at the opening exchanges and appear to forget everything said since.
        We take the newest and flip them back into reading order.
        """
        messages = list(session.messages.order_by('-created_at')[:limit])
        messages.reverse()
        return [
            {'role': msg.role, 'content': msg.content, 'id': str(msg.id)} for msg in messages
        ]

    @staticmethod
    def _tenant_of(session):
        """Whose AI key/budget this conversation spends.

        The student's own account is the authority here — never the stored
        ``session.tenant``, which originated from a client-supplied header and
        would otherwise let a user bill a tenant they don't belong to.
        """
        return (
            tenant_of_student(session.student)
            or session.tenant
            or getattr(session.course, 'tenant', None)
        )

    @staticmethod
    def process_question(session, question, image=None):
        """Answer a question without streaming (used by the simple endpoint)."""
        from .providers import complete_with_failover

        user_message = ChatService.add_message(session, 'user', question)
        if image:
            user_message.image = image
            user_message.save()

        tenant = ChatService._tenant_of(session)
        try:
            resolution = resolver.resolve(tenant, session.student)
        except resolver.AIUnavailable as exc:
            return {
                'message': ChatService.add_message(
                    session, 'assistant', unavailable_message(exc), model_used='unavailable'
                ),
                'success': False,
                'reason': exc.reason,
            }

        history = ChatService.get_session_history(session)
        messages = build_messages(session, history, resolution.settings_obj)

        try:
            used, content, usage, elapsed = complete_with_failover(resolution.chain, messages)
        except AIProviderError as exc:
            resolver.record_usage(
                tenant=tenant,
                student=session.student,
                session=session,
                resolved=resolution.provider,
                usage=Usage(),
                was_successful=False,
                error_message=str(exc),
            )
            return {
                'message': ChatService.add_message(
                    session,
                    'assistant',
                    UNAVAILABLE_TEMPLATE.format(reason=PROVIDER_ERROR_REASON),
                    model_used='error',
                ),
                'success': False,
                'reason': 'provider_error',
            }

        resolver.record_usage(
            tenant=tenant,
            student=session.student,
            session=session,
            resolved=used,
            usage=usage,
            response_time_ms=elapsed,
        )

        ai_message = ChatService.add_message(
            session,
            'assistant',
            content,
            model_used=public_model_label(used),
            tokens_used=usage.total_tokens,
            response_time_ms=elapsed,
        )
        return {'message': ai_message, 'success': True}

    @staticmethod
    def process_question_streaming(session, question, image=None):
        """Answer a question as a newline-delimited JSON stream.

        Yields ``{'content': delta, 'done': False}`` chunks and a terminal
        ``{'done': True, ...}`` object carrying the saved message id.
        """
        from .providers import stream_with_failover

        user_message = ChatService.add_message(session, 'user', question)
        if image:
            user_message.image = image
            user_message.save()

        tenant = ChatService._tenant_of(session)

        def generator():
            try:
                resolution = resolver.resolve(tenant, session.student)
            except resolver.AIUnavailable as exc:
                text = unavailable_message(exc)
                message = ChatService.add_message(
                    session, 'assistant', text, model_used='unavailable'
                )
                yield json.dumps(
                    {
                        'content': text,
                        'done': True,
                        'success': False,
                        'full_content': text,
                        'reason': exc.reason,
                        'message_id': str(message.id),
                    }
                ) + '\n'
                return

            history = ChatService.get_session_history(session)
            messages = build_messages(session, history, resolution.settings_obj)

            started = time.time()
            full_content = ''
            usage = Usage()
            # Which model ends up answering can change under us if the first
            # one fails before emitting anything, so track it for the metering.
            used = resolution.provider

            try:
                for rp, delta, chunk_usage in stream_with_failover(resolution.chain, messages):
                    used = rp
                    if chunk_usage is not None:
                        usage = chunk_usage
                    if delta:
                        full_content += delta
                        yield json.dumps({'content': delta, 'done': False}) + '\n'
            except AIProviderError as exc:
                resolver.record_usage(
                    tenant=tenant,
                    student=session.student,
                    session=session,
                    resolved=used,
                    usage=Usage(),
                    was_successful=False,
                    error_message=str(exc),
                )
                if not full_content:
                    text = UNAVAILABLE_TEMPLATE.format(reason=PROVIDER_ERROR_REASON)
                    message = ChatService.add_message(
                        session, 'assistant', text, model_used='error'
                    )
                    yield json.dumps(
                        {
                            'content': text,
                            'done': True,
                            'success': False,
                            'full_content': text,
                            'reason': 'provider_error',
                            'message_id': str(message.id),
                        }
                    ) + '\n'
                    return

            elapsed = int((time.time() - started) * 1000)

            # Streaming APIs often omit usage; approximate so budgets still move.
            if not usage.total_tokens and full_content:
                approx_out = max(1, len(full_content) // 4)
                approx_in = max(1, sum(len(m['content']) for m in messages) // 4)
                usage = Usage(
                    prompt_tokens=approx_in,
                    completion_tokens=approx_out,
                    total_tokens=approx_in + approx_out,
                )

            resolver.record_usage(
                tenant=tenant,
                student=session.student,
                session=session,
                resolved=used,
                usage=usage,
                response_time_ms=elapsed,
            )

            ai_message = ChatService.add_message(
                session,
                'assistant',
                full_content,
                model_used=public_model_label(used),
                tokens_used=usage.total_tokens,
                response_time_ms=elapsed,
            )
            yield json.dumps(
                {
                    'content': '',
                    'done': True,
                    'success': True,
                    'full_content': full_content,
                    'model': public_model_label(used),
                    'message_id': str(ai_message.id),
                }
            ) + '\n'

        return generator()
