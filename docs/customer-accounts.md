# Customer accounts and order history

Ordering as a guest always works. An account only keeps your history, so a customer who never signs up loses nothing.

## What an account is
One ServeFlow account works at every restaurant: a sign-in (email and password) plus a profile (name, phone). It is **separate from
restaurant users and the platform owner**:
* it has no restaurant membership and no platform rights, and an account with a customer profile **can't create a restaurant**;
* the customer routes only accept accounts that have a profile, and restaurant users get `403` there;
* the customer sign-in answers "Invalid email or password" for a wrong password, an unknown email **and** an email that belongs to a
  restaurant user, so account types can't be told apart. An email can only be used once; a person who is both uses two emails.

## Routes (`/api/v1/customers/`)
| Route | Purpose |
|---|---|
| `POST register/` | Create an account and sign in (`first_name`, `email`, `password`; optional `last_name`, `phone`). Password rules are Django's; throttled |
| `POST login/`, `POST logout/` | Session sign-in (CSRF enforced, same as the dashboard); sign-in is rate limited per IP and per email |
| `GET/PATCH me/` | Your name and phone (email isn't editable here) |
| `POST password/` | Needs the current password; this device stays signed in, other sessions end |
| `GET orders/` | Your orders newest first (`?active=1` for in-progress), each with a `track_token` for the normal order page |
| `GET orders/<public_id>/` | One of your orders (the same view as the order link, plus the token); someone else's is `404` |
| `POST orders/claim/` | Add a guest order to your account with its private link (`token`); an order that already belongs to another account is `409 already_linked` |

## How orders get linked
* **Signed in at checkout:** the new order is attached to the account automatically (the checkout recognises the session; CSRF is then
  required, which the front end already sends).
* **Placed as a guest:** open the order page while signed in and choose **Add to my account**. Only the order's private link can link it.
* Deleting an account never deletes the restaurant's orders; they simply stop belonging to an account.

## Pages
`customer/account.html` (sign in, create account, details, password, sign out), `customer/my-orders.html` (in progress, earlier orders,
each opening the normal order page where payment details and the review box live), a **Sign in / My orders** link in every page header,
and the checkout fills in your name and phone when you are signed in. The sign-in redirect (`?next=`) only accepts our own customer pages and
never a page that carries an order link.

## Not built yet
Email verification and password reset (they need an email service), deleting your own account, and saved addresses or favourite restaurants.
