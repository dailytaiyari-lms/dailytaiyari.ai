"""Syllabus & tagging tools, mounted at /api/v1/tenant-admin/intelligence/syllabus/."""
from django.urls import path

from . import syllabus_views as v

urlpatterns = [
    path('courses/<uuid:course_id>/tree/', v.CourseTreeView.as_view(), name='syllabus-tree'),
    path('courses/<uuid:course_id>/tree/estimate/', v.TreeEstimateView.as_view(),
         name='syllabus-tree-estimate'),
    path('courses/<uuid:course_id>/tree/build/', v.TreeBuildView.as_view(), name='syllabus-tree-build'),
    path('courses/<uuid:course_id>/tree/exam/', v.ExamMappingView.as_view(), name='syllabus-tree-exam'),
    path('courses/<uuid:course_id>/nodes/', v.NodeCreateView.as_view(), name='syllabus-node-create'),
    path('nodes/<uuid:node_id>/', v.NodeDetailView.as_view(), name='syllabus-node'),
    path('nodes/<uuid:node_id>/merge/', v.NodeMergeView.as_view(), name='syllabus-node-merge'),
    path('courses/<uuid:course_id>/skill-packs/', v.SkillPacksView.as_view(), name='syllabus-skill-packs'),
    path('courses/<uuid:course_id>/tagging/estimate/', v.TaggingEstimateView.as_view(),
         name='syllabus-tagging-estimate'),
    path('courses/<uuid:course_id>/tagging/run/', v.TaggingRunStartView.as_view(),
         name='syllabus-tagging-run'),
    path('jobs/<uuid:job_id>/', v.JobDetailView.as_view(), name='syllabus-job'),
    path('review/', v.ReviewListView.as_view(), name='syllabus-review'),
    path('review/bulk-accept/', v.ReviewBulkAcceptView.as_view(), name='syllabus-review-bulk-accept'),
    path('review/<uuid:tagging_id>/', v.ReviewDetailView.as_view(), name='syllabus-review-detail'),
    path('review/<uuid:tagging_id>/accept/', v.ReviewAcceptView.as_view(), name='syllabus-review-accept'),
    path('review/<uuid:tagging_id>/retag/', v.ReviewRetagView.as_view(), name='syllabus-review-retag'),
    path('review/<uuid:tagging_id>/add-to-tree/', v.ReviewAddToTreeView.as_view(),
         name='syllabus-review-add-to-tree'),
    path('items/<str:kind>/<uuid:item_id>/tags/', v.ItemTagsView.as_view(), name='syllabus-item-tags'),
]
