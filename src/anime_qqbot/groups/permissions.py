from anime_qqbot.qq.contracts import MemberRole, QQEvent


class PermissionPolicy:
    def __init__(self, bootstrap_identities: set[tuple[str, str]] | None = None) -> None:
        self._bootstrap = bootstrap_identities or set()

    def can_manage_group(self, event: QQEvent) -> bool:
        if not event.group_openid or not event.member_openid:
            return False
        return (
            event.member_role in {MemberRole.OWNER, MemberRole.ADMIN}
            or (
                event.group_openid,
                event.member_openid,
            )
            in self._bootstrap
        )
