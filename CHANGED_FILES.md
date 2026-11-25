# Files in this package
Copy these over your project, keeping the folder paths. Nothing else changed.

## New files
- `backend/apps/customers/__init__.py`
- `backend/apps/customers/apps.py`
- `backend/apps/customers/models.py`
- `backend/apps/customers/permissions.py`
- `backend/apps/customers/serializers.py`
- `backend/apps/customers/urls.py`
- `backend/apps/customers/views.py`
- `backend/apps/orders/lateness.py`
- `backend/tests/test_customers.py`
- `backend/tests/test_late_pickup.py`
- `docs/customer-accounts.md`
- `frontend/customer/account.html`
- `frontend/customer/js/account-helpers.js`
- `frontend/customer/js/account-link.js`
- `frontend/customer/js/account.js`
- `frontend/customer/js/my-orders.js`
- `frontend/customer/my-orders.html`
- `frontend/shared/js/late-policy.js`

## Edited files
- `backend/apps/orders/models.py`
- `backend/apps/orders/public_views.py`
- `backend/apps/orders/serializers.py`
- `backend/apps/orders/services.py`
- `backend/apps/orders/urls.py`
- `backend/apps/orders/views.py`
- `backend/apps/orders/workflow.py`
- `backend/apps/restaurants/models.py`
- `backend/apps/restaurants/serializers.py`
- `backend/apps/restaurants/services.py`
- `backend/config/settings/base.py`
- `backend/config/urls.py`
- `backend/tests/test_menu_public_api.py`
- `backend/tests/test_orders_public_api.py`
- `docs/api.md`
- `docs/orders-and-payments.md`
- `frontend/customer/js/checkout.js`
- `frontend/customer/js/marketplace.js`
- `frontend/customer/js/order.js`
- `frontend/customer/js/restaurant.js`
- `frontend/restaurant-dashboard/js/orders.js`
- `frontend/restaurant-dashboard/js/payment-account.js`
- `frontend/tests/helpers.test.mjs`

## After copying
1. `python manage.py makemigrations` then `python manage.py migrate` (new: customers app, late pickup fields on restaurants and orders, order.customer).
2. `pytest`
