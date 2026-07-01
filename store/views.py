from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.db.models import Q
from .models import Category, Product, Cart, CartItem, Order, OrderItem, Review
from .recommendations import get_content_based_recommendations, get_collaborative_recommendations, get_hybrid_recommendations
from django.db.models import Sum
from django.db.models.functions import ExtractMonth

# =========================================================================
# 1. CORE MARKETPLACE & SEARCH/CATEGORY CATALOG VIEWS
# =========================================================================
def home(request):
    categories = Category.objects.all()
    category_name = request.GET.get('category')
    search_query = request.GET.get('search_query') or request.POST.get('Search')

    products = Product.objects.filter(is_available=True)

    if category_name:
        products = products.filter(category__name__iexact=category_name)

    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) | 
            Q(description__icontains=search_query)
        )

    # --- UPDATED DYNAMIC HYBRID ML PIPELINE ---
    personalized_recommendations = []
    # Show recommendations on the home banner only when not actively searching/filtering
    if not category_name and not search_query:
        personalized_recommendations = get_hybrid_recommendations(request.user, num_recommendations=4)

    context = {
        'categories': categories,
        'products': products,
        'search_query': search_query,
        'selected_category': category_name,
        'personalized_recommendations': personalized_recommendations,
    }
    return render(request, 'store/home.html', context)


def product_detail_view(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    reviews = product.reviews.all().order_by('-created_at')

    # 1. Fire up the ML engine to fetch similar items
    similar_products = get_content_based_recommendations(product, num_recommendations=4)

    can_review = False
    if request.user.is_authenticated:
        can_review = Order.objects.filter(
            user=request.user,
            status='Delivered',
            items__product=product
        ).exists()

    context = {
        'product': product,
        'reviews': reviews,
        'can_review': can_review,
        'similar_products': similar_products, # <-- Added to context
    }
    return render(request, 'store/product_detail.html', context)


# =========================================================================
# 2. PRODUCT REVIEWS (VERIFIED DELIVERED BUYERS ONLY)
# =========================================================================
@login_required(login_url='user_login')
def add_review_view(request, product_id):
    if request.method == 'POST':
        product = get_object_or_404(Product, id=product_id)
        
        # Double-check backend verification layer safety
        has_delivered_order = Order.objects.filter(
            user=request.user,
            status='Delivered',
            items__product=product
        ).exists()
        
        if not has_delivered_order:
            messages.error(request, "You can only review products that have been delivered to you.")
            return redirect('profile')
            
        stars = int(request.POST.get('stars', 5))
        review_text = request.POST.get('review_text', '')
        review_image = request.FILES.get('review_image')
        
        Review.objects.create(
            product=product,
            user=request.user,
            stars=stars,
            review_text=review_text,
            review_image=review_image
        )
        messages.success(request, "Your review has been submitted successfully!")
    
    return redirect('profile')


# =========================================================================
# 3. SHOPPING CART ENGINE & SESSIONS
# =========================================================================
@login_required(login_url='user_login')
def cart_detail(request):
    cart, created = Cart.objects.get_or_create(user=request.user)
    return render(request, 'store/cart.html', {'cart': cart})


@login_required(login_url='user_login')
def add_to_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    cart, created = Cart.objects.get_or_create(user=request.user)
    cart_item, item_created = CartItem.objects.get_or_create(cart=cart, product=product)
    
    if not item_created:
        cart_item.quantity += 1
        cart_item.save()
        
    messages.success(request, f"{product.name} added to your cart.")
    return redirect('cart_detail')


# =========================================================================
# 4. ADVANCED CHECKOUT & ISOLATED "BUY NOW" LOGIC
# =========================================================================
@login_required(login_url='user_login')
def buy_now_view(request, product_id):
    # Skips modifying the background database cart, routes straight to checkout
    return redirect(f'/checkout/?buy_now={product_id}')


@login_required(login_url='user_login')
def checkout_view(request):
    buy_now_id = request.GET.get('buy_now')
    cart, created = Cart.objects.get_or_create(user=request.user)
    
    # Flow A: Single Item "Buy Now"
    if buy_now_id:
        product = get_object_or_404(Product, id=buy_now_id)
        price = product.discount_price if product.discount_price else product.price
        checkout_items = [{
            'product': product,
            'quantity': 1,
            'subtotal': price
        }]
        total_price = price
        
    # Flow B: Full Regular Cart Checkout
    else:
        if cart.items.count() == 0:
            messages.warning(request, "Your cart is empty. Add items first!")
            return redirect('home')
        
        checkout_items = cart.items.all()
        total_price = cart.total_price

    if request.method == 'POST':
        full_name = request.POST.get('full_name')
        phone_number = request.POST.get('phone_number')
        shipping_address = request.POST.get('shipping_address')
        city = request.POST.get('city')
        pincode = request.POST.get('pincode')

        # Generate a new master Order profile record
        order = Order.objects.create(
            user=request.user,
            full_name=full_name,
            phone_number=phone_number,
            shipping_address=shipping_address,
            city=city,
            pincode=pincode,
            total_amount=total_price
        )

        # Commit line items and reduce matching item stock
        if buy_now_id:
            OrderItem.objects.create(
                order=order,
                product=product,
                quantity=1,
                price=price
            )
            if product.stock >= 1:
                product.stock -= 1
                product.save()
        else:
            for item in cart.items.all():
                OrderItem.objects.create(
                    order=order,
                    product=item.product,
                    quantity=item.quantity,
                    price=item.product.discount_price if item.product.discount_price else item.product.price
                )
                if item.product.stock >= item.quantity:
                    item.product.stock -= item.quantity
                    item.product.save()
            
            # Wipe cart entries clean since they successfully checked out
            cart.items.all().delete()
        
        messages.success(request, f"Order #{order.id} placed successfully! Thank you for shopping.")
        return redirect('profile')

    context = {
        'checkout_items': checkout_items,
        'total_price': total_price,
        'buy_now_id': buy_now_id
    }
    return render(request, 'store/checkout.html', context)


# =========================================================================
# 5. USER ACCOUNTS & PROFILE ENGINE
# =========================================================================
def register_view(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Registration successful! Welcome to Desi Kart.")
            return redirect('home')
    else:
        form = UserCreationForm()
    return render(request, 'store/register.html', {'form': form})


def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, f"Welcome back, {username}!")
                return redirect('home')
        else:
            messages.error(request, "Invalid username or password.")
    else:
        form = AuthenticationForm()
    return render(request, 'store/login.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, "You have successfully logged out.")
    return redirect('home')


@login_required(login_url='user_login')
def profile_view(request):
    # Fetch all orders belonging to the user so they display on the profile dashboard
    orders = Order.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'store/profile.html', {'orders': orders})


# =========================================================================
# 6. MANAGEMENT DESK & STAFF DASHBOARD
# =========================================================================
@staff_member_required(login_url='user_login')
def admin_orders_dashboard(request):
    orders = Order.objects.all().order_by('-created_at')
    
    # Core Summary Indicators
    total_revenue = sum(order.total_amount for order in orders if order.status != 'Cancelled')
    pending_orders = orders.filter(status='Pending').count()
    
    # -------------------------------------------------------------------------
    # ANALYTICS PIPELINE A: Monthly Revenue Line Chart Data
    # -------------------------------------------------------------------------
    # Extracts months from completed orders in 2026
    monthly_sales_data = (
        Order.objects.filter(created_at__year=2026)
        .exclude(status='Cancelled')
        .annotate(month=ExtractMonth('created_at'))
        .values('month')
        .annotate(total=Sum('total_amount'))
        .order_by('month')
    )
    
    # Initialize monthly arrays mapped out for Chart.js (Jan to Dec)
    revenue_dataset = [0.0] * 12
    for entry in monthly_sales_data:
        month_idx = entry['month'] - 1  # Convert 1-12 to 0-11 index
        revenue_dataset[month_idx] = float(entry['total'] or 0.0)

    # -------------------------------------------------------------------------
    # ANALYTICS PIPELINE B: Top-Selling Categories Pie Chart Data
    # -------------------------------------------------------------------------
    category_sales_dict = {}
    order_items = OrderItem.objects.select_related('product__category', 'order').all()
    
    for item in order_items:
        if item.order.status != 'Cancelled' and item.product.category:
            cat_name = item.product.category.name
            item_total = float(item.price * item.quantity)
            category_sales_dict[cat_name] = category_sales_dict.get(cat_name, 0.0) + item_total

    category_labels = list(category_sales_dict.keys())
    category_data = list(category_sales_dict.values())

    context = {
        'orders': orders,
        'total_revenue': total_revenue,
        'pending_orders': pending_orders,
        # Chart payloads
        'revenue_dataset': revenue_dataset,
        'category_labels': category_labels,
        'category_data': category_data,
    }
    return render(request, 'store/admin_dashboard.html', context)


@staff_member_required(login_url='user_login')
def update_order_status(request, order_id):
    if request.method == 'POST':
        order = get_object_or_404(Order, id=order_id)
        new_status = request.POST.get('status')
        
        # Guard against fake states using choices lists validation
        if new_status in dict(Order.STATUS_CHOICES):
            order.status = new_status
            order.save()
            messages.success(request, f"Order #{order.id} status updated to {new_status}.")
            
    return redirect('admin_orders_dashboard')

# =========================================================================
# 7. CART QUANTITY ADJUSTMENT CONTROLLER
# =========================================================================
@login_required(login_url='user_login')
def update_cart_quantity(request, item_id, action):
    # Fetch the specific cart item safely confirming it belongs to this logged-in user
    cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
    
    if action == 'increment':
        cart_item.quantity += 1
        cart_item.save()
        messages.success(request, f"Increased quantity of {cart_item.product.name}.")
    elif action == 'decrement':
        cart_item.quantity -= 1
        if cart_item.quantity <= 0:
            cart_item.delete()
            messages.info(request, f"Removed {cart_item.product.name} from cart.")
        else:
            cart_item.save()
            messages.success(request, f"Decreased quantity of {cart_item.product.name}.")
    elif action == 'remove':
        cart_item.delete()
        messages.info(request, f"Removed {cart_item.product.name} from cart.")
        
    return redirect('cart_detail')