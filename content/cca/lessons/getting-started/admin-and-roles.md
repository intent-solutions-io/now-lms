# Roles, admin & instructor access

This lesson is for **administrators and instructors**. It explains the roles on
Intent Solutions Learn and the admin tasks you'll do most often — starting with
the one that unblocks new learners: **activating accounts**.

## The four roles

Every user has a role (`Usuario.tipo`):

- **admin** — full access; bypasses every permission gate. Runs the platform.
- **instructor** — creates and manages courses, sections, evaluations, and
  questions.
- **moderator** — moderation surfaces (forum, flagged messages, blog).
- **student** — enrolls in and takes courses.

Two status flags sit alongside the role:

- **active / inactive** (`activo`) — inactive users cannot log in.
- **email-verified** (`correo_electronico_verificado`).

## Logging in and reaching the admin panel

Sign in at **`/user/login`**. Your role decides what you can reach:

- Admins: the admin panel at **`/admin/panel`** (and an admin view of the shared
  dashboard at `/home/panel`).
- Instructors: the instructor area at **`/instructor`**.

## Activating new users (the #1 task today)

With the current configuration, **self-registered students land inactive** and
need an admin to switch them on. From the admin area:

- **`/admin/users/list`** — all users.
- **`/admin/users/list_inactive`** — accounts waiting to be activated.
- **`/admin/users/list_unverified`** — accounts with unverified email.
- **Activate:** `POST /admin/users/set_active/<user_id>` (the "activate" button).
- **Deactivate:** `POST /admin/users/set_inactive/<user_id>`.
- **Verify email manually:** `POST /admin/users/verify_email/<user_id>` — useful
  while email sending isn't configured.
- **Delete:** `POST /admin/users/delete/<user_id>`.

## Creating staff and changing roles

- **Create a user directly** (admin only): **`/user/new_user`**. This creates an
  **active, email-verified** account with the **student** role.
- **Elevate a role** (student → instructor / moderator / admin): open the user's
  admin profile page at **`/user/<username>`** and change their role there.

## Making self-service sign-up work end to end

If you'd rather not activate every new learner by hand, an admin can:

1. **Configure mail** at `/setting/mail` (verify it at `/setting/mail/verify`), then
2. **Enable email verification** in `/setting/general`, so a confirmation email
   both verifies and activates each new account; **or**
3. Enable *login for unverified users* so accounts activate (with limited
   access) on first login.

## Further reading

- Setup & configuration: `bmosoluciones.github.io/now-lms/setup/`,
  `bmosoluciones.github.io/now-lms/setup-conf/`
- Mail configuration: `bmosoluciones.github.io/now-lms/mail/`
