import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from django.contrib.auth.models import User
from .models import Product, Review

def get_content_based_recommendations(target_product, num_recommendations=4):
    """
    Analyzes product metadata (name + description) using TF-IDF and 
    Cosine Similarity to return the top similar available products.
    """
    # 1. Fetch all other available products from the database
    all_products = list(Product.objects.filter(is_available=True))
    
    if len(all_products) <= 1:
        return []

    # 2. Convert database queryset into a Pandas DataFrame for processing
    data = []
    for p in all_products:
        # Combine name and description into a single text metadata string
        combined_features = f"{p.name} {p.category.name if p.category else ''} {p.description or ''}"
        data.append({
            'id': p.id,
            'metadata': combined_features,
            'object': p
        })
    
    df = pd.DataFrame(data)

    # 3. Initialize the TF-IDF Vectorizer (removes common English stop words)
    tfidf = TfidfVectorizer(stop_words='english')
    tfidf_matrix = tfidf.fit_transform(df['metadata'])

    # 4. Compute the pairwise Cosine Similarity matrix across all products
    cosine_sim = cosine_similarity(tfidf_matrix, tfidf_matrix)

    # 5. Find the index of our target product inside the DataFrame
    try:
        target_idx = df[df['id'] == target_product.id].index[0]
    except IndexError:
        return []

    # 6. Extract similarity scores for this product and sort them (highest first)
    sim_scores = list(enumerate(cosine_sim[target_idx]))
    sim_scores = sorted(sim_scores, key=lambda x: x[1], reverse=True)

    # 7. Grab the top matches (skipping the first one, since it's the product itself)
    recommended_indices = []
    for idx, score in sim_scores:
        if df.iloc[idx]['id'] != target_product.id:
            recommended_indices.append(idx)
        if len(recommended_indices) == num_recommendations:
            break

    # 8. Extract the actual Django Product model objects out of the DataFrame
    recommended_products = [df.iloc[i]['object'] for i in recommended_indices]
    
    return recommended_products

#collaborative filtering imports
import numpy as np
from store.models import OrderItem

def get_collaborative_recommendations(user, num_recommendations=4):
    """
    Computes User-Based Collaborative Filtering using User-Product ratings matrix
    to recommend products to a logged-in shopper.
    """
    # 1. Base Safeguard: If user is logged out, collaborative filtering cannot run
    if not user.is_authenticated:
        return []

    # 2. Extract relevant transactional data from the system database
    all_reviews = Review.objects.all()
    if not all_reviews.exists():
        return []

    # 3. Build an structure of users and products
    user_ids = list(User.objects.values_list('id', flat=True))
    product_objects = list(Product.objects.filter(is_available=True))
    product_ids = [p.id for p in product_objects]

    if len(user_ids) < 2 or len(product_ids) == 0:
        return []

    # 4. Construct a User-Item rating pivot matrix initialized with zeros
    # Rows = Users, Columns = Products
    matrix = pd.DataFrame(0.0, index=user_ids, columns=product_ids)

    for review in all_reviews:
        if review.product_id in matrix.columns and review.user_id in matrix.index:
            matrix.loc[review.user_id, review.product_id] = float(review.stars)

    # 5. Also incorporate purchase history as a minor implicit signal (assign score of 3 if bought but not rated)
    all_order_items = OrderItem.objects.select_related('order').all()
    for item in all_order_items:
        u_id = item.order.user_id
        p_id = item.product_id
        if p_id in matrix.columns and u_id in matrix.index:
            # Only elevate if the cell is currently unrated (zero)
            if matrix.loc[u_id, p_id] == 0.0:
                matrix.loc[u_id, p_id] = 3.0

    # 6. Compute user-to-user cosine similarity matrix
    try:
        user_sim = cosine_similarity(matrix)
        user_sim_df = pd.DataFrame(user_sim, index=user_ids, columns=user_ids)
    except Exception:
        return []

    # 7. Identify top similar neighbors for our active target user (excluding themselves)
    if user.id not in user_sim_df.index:
        return []
        
    similar_users = user_sim_df[user.id].drop(user.id).sort_values(ascending=False)
    
    # Filter neighbors that have at least some positive taste overlap
    top_neighbors = similar_users[similar_users > 0.1].index.tolist()

    if not top_neighbors:
        return []

    # 8. Aggregate product scores weighted by neighbor similarity scores
    user_read_items = matrix.loc[user.id]
    unviewed_products = user_read_items[user_read_items == 0.0].index.tolist()

    if not unviewed_products:
        return []

    product_scores = {}
    for p_id in unviewed_products:
        score_sum = 0.0
        sim_weight_sum = 0.0
        
        for neighbor in top_neighbors:
            neighbor_rating = matrix.loc[neighbor, p_id]
            if neighbor_rating > 0:
                sim_score = user_sim_df.loc[user.id, neighbor]
                score_sum += neighbor_rating * sim_score
                sim_weight_sum += sim_score
                
        if sim_weight_sum > 0:
            product_scores[p_id] = score_sum / sim_weight_sum

    # 9. Sort final scores and extract top django primary key match models
    sorted_products = sorted(product_scores.items(), key=lambda x: x[1], reverse=True)
    recommended_ids = [p_id for p_id, score in sorted_products[:num_recommendations]]

    # Maintain explicit sort orders when fetching from DB
    recommended_products = [p for p_id in recommended_ids for p in product_objects if p.id == p_id]

    return recommended_products

#hybrid recommendation engine
def get_hybrid_recommendations(user, current_product=None, num_recommendations=4):
    """
    Hybrid Recommendation Engine: Blends Collaborative and Content-Based filtering.
    Handles the 'Cold Start' problem seamlessly for new or inactive shoppers.
    """
    recommendations = []
    
    # 1. Try to get Collaborative Filtering results first if user is logged in
    if user and user.is_authenticated:
        recommendations = get_collaborative_recommendations(user, num_recommendations)
        
    # 2. Cold Start Fallback: If no collaborative matches found (new user), use Content-Based matching
    if not recommendations:
        if current_product:
            # If viewing a product, get items similar to it
            recommendations = get_content_based_recommendations(current_product, num_recommendations)
        else:
            # On the homepage, fall back to high-quality available items ordered by rating/popularity
            all_available = Product.objects.filter(is_available=True)
            # Sort products based on their computed average rating property
            recommendations = sorted(
                all_available, 
                key=lambda p: (p.average_rating, p.total_reviews), 
                reverse=True
            )[:num_recommendations]
            
    return recommendations