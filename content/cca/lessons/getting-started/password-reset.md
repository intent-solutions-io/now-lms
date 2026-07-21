# Resetting your password

If you've forgotten your password, here's how recovery works — and what to do if
the self-service option isn't available yet.

## Self-service reset (when email is configured)

1. On the login page (`/user/login`), click **"Forgot password?"**. This takes
   you to **`/user/forgot_password`**.
2. Enter your account email. The platform emails you a **reset link** containing
   a one-time token.
3. Open the link — **`/user/reset_password/<token>`** — and set a new password.
4. Log in with your new password.

The token is single-use and time-limited; if it expires, just request another.

## If you don't see "Forgot password?"

The self-service link only appears when the site's **email sending is
configured**. If it's missing, password recovery by email isn't available yet —
in that case:

- Ask an **administrator** to help. An admin can reset a user's password from the
  user's admin profile page (`/user/<username>` → change password), or activate
  and reissue credentials.

## For administrators

To enable self-service password reset for everyone, configure and verify mail:

- Set up the mail server at **`/setting/mail`**, then confirm it at
  **`/setting/mail/verify`**.

Once mail is verified, the "Forgot password?" link appears automatically on the
login page.

## Further reading

- Mail configuration: `bmosoluciones.github.io/now-lms/mail/`
