from django.urls import path
from . import views
from django.contrib.auth import views as auth_views
from store import views as store_views

urlpatterns = [
    path('', views.home, name='home'),
    path('user_login/', views.login_view, name='user_login'),
    path('register/', views.register_view, name='register'),
    path('user_logout/', views.logout_view, name='user_logout'),

    # Cart Operations
    path('cart/', views.cart_detail, name='cart_detail'),
    path('cart/add/<int:product_id>/', views.add_to_cart, name='add_to_cart'),
    path('cart/update/<int:item_id>/<str:action>/', views.update_cart_quantity, name='update_cart_quantity'),

    path('checkout/', views.checkout_view, name='checkout'),

    path('profile/', views.profile_view, name='profile'),

    path('product/<int:product_id>/', views.product_detail_view, name='product_detail'),
    path('buy-now/<int:product_id>/', views.buy_now_view, name='buy_now'),

    path('admin-panel/orders/', views.admin_orders_dashboard, name='admin_orders_dashboard'),
    path('admin-panel/orders/update/<int:order_id>/', views.update_order_status, name='update_order_status'),

    path('product/<int:product_id>/add-review/', views.add_review_view, name='add_review'),

    # =========================================================================
    # ENHANCED SIGNUP/OTP FLOW ROUTES
    # =========================================================================
    path('register/email/', store_views.send_signup_otp, name='send_signup_otp'),
    path('register/verify/', store_views.verify_and_register, name='verify_and_register'),

    # =========================================================================
    # CORE DJANGO PASSWORD RESET INFRASTRUCTURE ROUTES
    # =========================================================================
    path('password-reset/', 
         auth_views.PasswordResetView.as_view(template_name='store/password_reset.html'), 
         name='password_reset'),
         
    path('password-reset/done/', 
         auth_views.PasswordResetDoneView.as_view(template_name='store/password_reset_done.html'), 
         name='password_reset_done'),
         
    path('password-reset-confirm/<uidb64>/<token>/', 
         auth_views.PasswordResetConfirmView.as_view(template_name='store/password_reset_confirm.html'), 
         name='password_reset_confirm'),
         
    path('password-reset-complete/', 
         auth_views.PasswordResetCompleteView.as_view(template_name='store/password_reset_complete.html'), 
         name='password_reset_complete'),
]