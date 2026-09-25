# SPDX-License-Identifier: Apache-2.0

"""Product guardrails for the legacy course communication surfaces."""


def test_course_forum_and_internal_messages_are_off_when_disabled(app):
    app.config["ENABLE_COURSE_COMMUNICATION"] = False
    client = app.test_client()

    assert client.get("/course/NOPE/forum").status_code == 404
    assert client.get("/course/NOPE/messages").status_code == 404
    assert client.get("/user/messages").status_code == 404


def test_course_communication_can_be_reenabled_for_migration(app):
    app.config["ENABLE_COURSE_COMMUNICATION"] = True
    client = app.test_client()

    # The feature guard is bypassed; normal authentication/authorization still
    # applies to the legacy routes.
    assert client.get("/course/NOPE/forum").status_code != 404
