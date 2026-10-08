from django.urls import path

from shop import views

urlpatterns = [
    path("sign-up/", views.sign_up),
    path("confirm/<str:token>/", views.confirm, name="confirm"),
]
