from .models import Category

def global_categories(request):
    return {
        'categories': Category.objects.all()
    }