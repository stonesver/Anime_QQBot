from datetime import UTC, datetime

import pytest

from anime_qqbot.groups.permissions import PermissionPolicy
from anime_qqbot.qq.contracts import MemberRole, QQEvent, QQEventType


@pytest.mark.parametrize(
    ("role", "bootstrap", "allowed"),
    [
        (MemberRole.OWNER, False, True),
        (MemberRole.ADMIN, False, True),
        (MemberRole.MEMBER, False, False),
        (MemberRole.MEMBER, True, True),
    ],
)
def test_group_management_permission_matrix(
    role: MemberRole, bootstrap: bool, allowed: bool
) -> None:
    event = QQEvent(
        "event",
        QQEventType.GROUP_AT_MESSAGE,
        datetime.now(UTC),
        group_openid="group",
        member_openid="member",
        member_role=role,
    )
    identities = {("group", "member")} if bootstrap else set()
    assert PermissionPolicy(identities).can_manage_group(event) is allowed
