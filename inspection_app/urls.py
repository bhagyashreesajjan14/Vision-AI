"""
URL patterns for inspection_app (both UI views and REST API endpoints).
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views_ui, views_api

router = DefaultRouter()
router.register(r'products', views_api.ProductViewSet, basename='api-product')
router.register(r'inspections', views_api.InspectionItemViewSet, basename='api-inspection')

urlpatterns = [
    # UI Views & Role Authentication Portals
    path('', views_ui.dashboard_view, name='dashboard'),
    path('login/', views_ui.login_hub_view, name='login'),
    path('login/admin/', views_ui.admin_login_view, name='login_admin'),
    path('login/engineer/', views_ui.engineer_login_view, name='login_engineer'),
    path('login/supervisor/', views_ui.supervisor_login_view, name='login_supervisor'),
    path('logout/', views_ui.logout_view, name='logout'),
    path('products/', views_ui.products_view, name='products'),
    path('inspect/single/', views_ui.inspect_single_view, name='inspect_single'),
    path('inspect/batch/', views_ui.inspect_batch_view, name='inspect_batch'),
    path('batches/<uuid:batch_id>/', views_ui.batch_detail_view, name='batch_detail'),
    path('history/', views_ui.history_view, name='history'),
    path('insights/', views_ui.quality_insights_view, name='quality_insights'),
    path('inspections/<uuid:inspection_id>/', views_ui.inspection_detail_view, name='inspection_detail'),
    path('inspections/<uuid:inspection_id>/traceability/', views_ui.inspection_traceability_export, name='inspection_traceability'),
    path('evaluation/', views_ui.evaluation_view, name='evaluation'),
    path('batches/<uuid:batch_id>/export/csv/', views_ui.export_batch_csv_view, name='export_batch_csv'),
    path('batches/<uuid:batch_id>/export/pdf/', views_ui.export_batch_pdf_view, name='export_batch_pdf'),

    # REST API Endpoints
    path('api/', include(router.urls)),
    path('api/inspections/single/', views_api.SingleInspectionAPIView.as_view(), name='api_single_inspect'),
    path('api/inspections/batch/', views_api.BatchInspectionAPIView.as_view(), name='api_batch_inspect'),
    path('api/batches/<uuid:batch_id>/status/', views_api.BatchStatusAPIView.as_view(), name='api_batch_status'),
]

