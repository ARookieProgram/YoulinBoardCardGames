"""管理员账号管理接口（`/api/admins/`）。

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/admins/` | **超级管理员** | 列表：关键字 / 角色 / 状态过滤 + 排序 + 分页 |
| POST | `/api/admins/` | **超级管理员** | 新建管理员 |
| GET | `/api/admins/overview/` | **超级管理员** | 概览：总数 / 启用 / 停用 / 超级管理员数 |
| GET | `/api/admins/<id>/` | **超级管理员** | 详情 |
| PATCH | `/api/admins/<id>/` | **超级管理员** | 改资料与角色（账号名不可改） |
| POST | `/api/admins/<id>/status/` | **超级管理员** | 启用 / 停用 |
| POST | `/api/admins/<id>/password/` | **超级管理员** | 重置他人的口令 |
| DELETE | `/api/admins/<id>/` | **超级管理员** | 删除 |
| POST | `/api/admins/me/password/` | **任意登录管理员** | 改自己的口令（需原口令） |

为什么整块都收在超级管理员这一层
--------------------------------

管理员账号是**权限的源头**：能改管理员的人等于能改所有人的权限。所以
`/api/admins/` 除"改自己的口令"外一律只对超级管理员开放（`IsSuperAdmin`），
前端也把该页面的路由标成 `requiresSuperAdmin`。无权限返回 `10003`、
未登录返回 `10002`，两者前端处理方式不同。

两条自锁护栏（服务端自己做，不依赖前端置灰）
--------------------------------------------

判序固定为**先"最后一个超级管理员"、再"是不是自己"**，两个码都因此可达：

1. **最后一个启用中的超级管理员**不能被停用 / 删除 / 降级（`15005`）。
   只剩一位超级管理员时，他对自己动手拿到的就是这句话——
   比笼统的"不能对自己操作"更准确。
2. **不能对自己动手**（停用 / 删除 / 给自己降级 → `15004`）。
   还有别的超级管理员时，也不能把自己停掉：停用后下一个请求就会因为
   `is_active=False` 被 401 拒掉，只能让别人把自己开回来。

"最后一个"的口径是 `effective_role`（`is_superuser=True` 的历史行也算），
与 `AdminUser.has_role_at_least()` 保持一致；判的时候把目标自己排除在外。

> 第 1 条在当前权限口径下会不会是死代码？不会：它正是
> "仅剩一位超级管理员时对自己动手"这条路径的判据。将来若把 `/api/admins/`
> 放宽到 `admin` 及以上，它还会额外拦住"普通管理员停掉最后一个超级管理员"，
> 所以这道护栏要留在服务端，而不是只靠前端置灰。

口令相关的两条固定动作
----------------------

* 改口令（本人改或超级管理员重置）之后，该管理员**已签发的 refresh 令牌
  全部进黑名单**（`_revoke_refresh_tokens`），也就是其它设备需要重新登录。
  access 是 JWT，无状态，在过期前仍然有效——这是 JWT 的固有边界，
  见 `README.md` §5.5。
* 口令强度一律走 Django 的 `AUTH_PASSWORD_VALIDATORS`（见 `serializers_admin`）。
"""

from __future__ import annotations

import logging
from typing import Any, cast

from django.db.models import Q
from django.db.models.query import QuerySet
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import AdminUser
from apps.accounts.permissions import IsSuperAdmin
from apps.common import response as envelope
from apps.common.pagination import page_payload

from .exceptions import (
    AdminLastSuperAdmin,
    AdminNotFound,
    AdminSelfOperation,
)
from .serializers_admin import (
    ADMIN_ROLE_ALL,
    ADMIN_STATUS_ALL,
    AdminCreateSerializer,
    AdminListQuerySerializer,
    AdminPasswordSerializer,
    AdminStatusSerializer,
    AdminUpdateSerializer,
    SelfPasswordSerializer,
    admin_row,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- 内部助手


def _actor(request: Request) -> AdminUser:
    """当前操作人。

    `IsAuthenticated` + `AUTH_USER_MODEL = "accounts.AdminUser"` 已保证
    `request.user` 是 `AdminUser`（SimpleJWT 取的就是这张表），这里只是把这个
    不变式告诉类型检查器——不做运行时判断，因为"到了这里还不是 AdminUser"
    意味着认证层坏了，用 `assert` 反而会在 `-O` 下被剥掉。
    """
    return cast(AdminUser, request.user)


def _get_admin_or_404(admin_id: int) -> AdminUser:
    """按主键取管理员，取不到抛 `AdminNotFound`（15001 / 404）。"""
    target = AdminUser.objects.filter(pk=admin_id).first()
    if target is None:
        raise AdminNotFound(admin_id)
    return target


def _enabled_super_admin_count(*, exclude_pk: int | None = None) -> int:
    """启用中的超级管理员数量（可排除一个）。

    刻意**不**只看 `role`：`effective_role` 把 `is_superuser=True` 的历史行
    也算作超级管理员。若只数 `role=super_admin`，一个"is_superuser 为真但
    role 还没升上来"的账号会被误判成不存在，护栏就漏了。
    """
    queryset = AdminUser.objects.filter(
        Q(role=AdminUser.Role.SUPER_ADMIN) | Q(is_superuser=True),
        status=AdminUser.Status.ACTIVE,
    )
    if exclude_pk is not None:
        queryset = queryset.exclude(pk=exclude_pk)
    return queryset.count()


def _assert_not_self(actor: AdminUser, target: AdminUser, message: str) -> None:
    """拦下"对自己动手"。"""
    if actor.pk == target.pk:
        raise AdminSelfOperation(message)


def _assert_not_last_super(target: AdminUser) -> None:
    """拦下"把最后一个启用中的超级管理员弄没"。

    只在目标**此刻**确实是启用中的超级管理员时才判：停用一个运营、
    或者停用一个已经停用的超级管理员，都不受影响。
    """
    if target.effective_role != AdminUser.Role.SUPER_ADMIN:
        return
    if target.status != AdminUser.Status.ACTIVE:
        return
    if _enabled_super_admin_count(exclude_pk=target.pk) == 0:
        raise AdminLastSuperAdmin()


def _revoke_refresh_tokens(admin: AdminUser) -> int:
    """把该管理员已签发的 refresh 令牌全部拉黑，返回本次新拉黑的条数。

    改口令必须让旧登录态失效，否则"改了密码但别人还能用"——refresh 是
    长有效期（默认 7 天）的，不主动拉黑等于没改。
    """
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    revoked = 0
    for token in OutstandingToken.objects.filter(user=admin):
        _, created = BlacklistedToken.objects.get_or_create(token=token)
        if created:
            revoked += 1
    return revoked


# ---------------------------------------------------------------- 视图


class AdminListView(APIView):
    """`GET /api/admins/` 列表、`POST /api/admins/` 新建。"""

    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request: Request) -> Response:
        """按关键字 / 角色 / 状态过滤管理员，分页返回。"""
        query = AdminListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params: dict[str, Any] = dict(query.validated_data)

        queryset: QuerySet[AdminUser] = AdminUser.objects.all()

        keyword: str = params["keyword"].strip()
        if keyword:
            queryset = queryset.filter(
                Q(username__icontains=keyword)
                | Q(nickname__icontains=keyword)
                | Q(email__icontains=keyword)
            )

        if params["role"] != ADMIN_ROLE_ALL:
            if params["role"] == AdminUser.Role.SUPER_ADMIN:
                # 与 `effective_role` 同一口径。
                queryset = queryset.filter(
                    Q(role=AdminUser.Role.SUPER_ADMIN) | Q(is_superuser=True)
                )
            else:
                queryset = queryset.filter(role=params["role"], is_superuser=False)

        if params["status"] != ADMIN_STATUS_ALL:
            queryset = queryset.filter(status=params["status"])

        total = queryset.count()
        page: int = params["page"]
        page_size: int = params["page_size"]
        offset = (page - 1) * page_size
        # 加 `-id` 作为稳定次序：同一天创建的账号按时间排会并列，
        # 翻页时顺序不稳定会出现"某一行两页都出现 / 都没出现"。
        rows = list(queryset.order_by(params["ordering"], "-id")[offset : offset + page_size])

        return envelope.ok(
            page_payload(
                items=[admin_row(row) for row in rows],
                total=total,
                page=page,
                page_size=page_size,
            )
        )

    def post(self, request: Request) -> Response:
        """新建一个管理员（默认启用；口令强度按 Django 校验器判定）。"""
        serializer = AdminCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data: dict[str, Any] = dict(serializer.validated_data)

        role: str = data["role"]
        if role == AdminUser.Role.SUPER_ADMIN:
            # `create_superuser` 会强制 role/is_staff/is_superuser 三者一致，
            # 避免出现"is_superuser=True 但 role=operator"这种自相矛盾的行。
            target = AdminUser.objects.create_superuser(
                username=data["username"],
                password=data["password"],
                email=data["email"],
                nickname=data["nickname"],
                remark=data["remark"],
            )
        else:
            target = AdminUser.objects.create_user(
                username=data["username"],
                password=data["password"],
                email=data["email"],
                nickname=data["nickname"],
                role=role,
                remark=data["remark"],
            )

        logger.info(
            "新建管理员 operator=%s target=%s role=%s",
            _actor(request).username,
            target.username,
            target.effective_role,
        )
        return envelope.created(admin_row(target), message="已创建管理员")


class AdminOverviewView(APIView):
    """`GET /api/admins/overview/` —— 列表页顶部的概览数字。"""

    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request: Request) -> Response:
        """返回管理员总数 / 启用 / 停用 / 超级管理员数。"""
        total = AdminUser.objects.count()
        active = AdminUser.objects.filter(status=AdminUser.Status.ACTIVE).count()
        return envelope.ok(
            {
                "total_admins": total,
                "active_admins": active,
                "disabled_admins": total - active,
                # "超级管理员"按 effective_role 口径统计，与权限判断一致。
                "super_admins": AdminUser.objects.filter(
                    Q(role=AdminUser.Role.SUPER_ADMIN) | Q(is_superuser=True)
                ).count(),
            }
        )


class AdminDetailView(APIView):
    """`/api/admins/<id>/` 的详情 / 改资料 / 删除。"""

    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request: Request, admin_id: int) -> Response:
        """返回一个管理员的资料。"""
        return envelope.ok(admin_row(_get_admin_or_404(admin_id)))

    def patch(self, request: Request, admin_id: int) -> Response:
        """改资料与角色。

        账号名不可改（见 `serializers_admin` 的模块文档）；
        降级别人之前要过"最后一个超级管理员"这道护栏。
        """
        actor = _actor(request)
        target = _get_admin_or_404(admin_id)
        serializer = AdminUpdateSerializer(target, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data: dict[str, Any] = dict(serializer.validated_data)

        changed: list[str] = []

        if "nickname" in data and data["nickname"] != target.nickname:
            target.nickname = data["nickname"]
            changed.append("nickname")
        if "email" in data and data["email"] != target.email:
            target.email = data["email"]
            changed.append("email")
        if "remark" in data and data["remark"] != target.remark:
            target.remark = data["remark"]
            changed.append("remark")

        new_role = data.get("role")
        if new_role is not None and new_role != target.role:
            if new_role != AdminUser.Role.SUPER_ADMIN:
                # 把超级管理员降成普通角色：先过两道自锁护栏。
                # 顺序是"先判最后一个、再判是不是自己"：只剩一位超级管理员时，
                # 更准确的提示是"他是最后一个"（15005），而不是笼统的"不能对自己操作"。
                _assert_not_last_super(target)
                _assert_not_self(actor, target, "不能降低自己的角色")
            target.role = new_role
            # `is_superuser` / `is_staff` 必须与 role 同进同退，否则
            # `effective_role` 仍然把这个人当超级管理员（权限判断用它）。
            target.is_superuser = new_role == AdminUser.Role.SUPER_ADMIN
            target.is_staff = target.is_superuser
            changed.extend(["role", "is_superuser", "is_staff"])

        if not changed:
            return envelope.ok(admin_row(target), message="没有需要修改的内容")

        target.save()
        logger.info(
            "修改管理员 operator=%s target=%s fields=%s",
            actor.username,
            target.username,
            ",".join(changed),
        )
        return envelope.ok(admin_row(target), message="已保存")

    def delete(self, request: Request, admin_id: int) -> Response:
        """删除一个管理员。

        是**物理删除**，不是停用：确实要"留人不留号"时用停用（状态开关），
        删除只用于建错了、或者离职后要清干净的情况。历史痕迹不会因此丢失——
        `PlayerBan.operator` 是 `SET_NULL`，另存了 `operator_name` 快照。
        """
        actor = _actor(request)
        target = _get_admin_or_404(admin_id)

        _assert_not_last_super(target)
        _assert_not_self(actor, target, "不能删除自己的账号")

        payload = {"id": target.pk, "username": target.username}
        target.delete()
        logger.info("删除管理员 operator=%s target_id=%s", actor.username, payload["id"])
        return envelope.ok(payload, message="已删除该管理员")


class AdminStatusView(APIView):
    """`POST /api/admins/<id>/status/` —— 启用 / 停用。"""

    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def post(self, request: Request, admin_id: int) -> Response:
        """切换启用状态。

        停用后该账号**立刻**登不进来：SimpleJWT 校验 `is_active`，
        而 `AdminUser.save()` 会把 `is_active` 与 `status` 对齐。
        """
        serializer = AdminStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status: str = dict(serializer.validated_data)["status"]

        actor = _actor(request)
        target = _get_admin_or_404(admin_id)

        if new_status == target.status:
            return envelope.ok(admin_row(target), message="状态未变化")

        if new_status == AdminUser.Status.DISABLED:
            _assert_not_last_super(target)
            _assert_not_self(actor, target, "不能停用自己的账号")

        target.status = new_status
        # `save()` 会同步 is_active；这里显式全量保存，别用 update_fields
        # 漏掉 is_active，否则 Django 仍认为账号有效（登录还能过）。
        target.save()

        logger.info(
            "管理员状态变更 operator=%s target=%s status=%s",
            actor.username,
            target.username,
            new_status,
        )
        message = "已启用该管理员" if new_status == AdminUser.Status.ACTIVE else "已停用该管理员"
        return envelope.ok(admin_row(target), message=message)


class AdminPasswordView(APIView):
    """`POST /api/admins/<id>/password/` —— 超级管理员重置他人口令。"""

    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def post(self, request: Request, admin_id: int) -> Response:
        """把目标账号的口令改成新口令，并吊销它已签发的 refresh 令牌。"""
        target = _get_admin_or_404(admin_id)
        serializer = AdminPasswordSerializer(target, data=request.data)
        serializer.is_valid(raise_exception=True)
        new_password: str = dict(serializer.validated_data)["new_password"]

        target.set_password(new_password)
        target.save()
        revoked = _revoke_refresh_tokens(target)

        logger.info(
            "重置管理员口令 operator=%s target=%s revoked_tokens=%s",
            _actor(request).username,
            target.username,
            revoked,
        )
        return envelope.ok(
            {"id": target.pk, "username": target.username, "revoked_tokens": revoked},
            message="已重置密码，该账号需要重新登录",
        )


class MyPasswordView(APIView):
    """`POST /api/admins/me/password/` —— 本人改口令（任意登录管理员）。

    这是 `/api/admins/` 下**唯一**不要求超级管理员的端点：运营与普通管理员
    也要能改自己的口令，否则只能找超级管理员重置。
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        """核对原口令后改口令，并吊销自己已签发的 refresh 令牌。"""
        admin = _actor(request)
        serializer = SelfPasswordSerializer(data=request.data, context={"admin": admin})
        serializer.is_valid(raise_exception=True)
        new_password: str = dict(serializer.validated_data)["new_password"]

        admin.set_password(new_password)
        admin.save()
        revoked = _revoke_refresh_tokens(admin)

        logger.info(
            "管理员修改自己的口令 username=%s revoked_tokens=%s",
            admin.username,
            revoked,
        )
        return envelope.ok(
            {"id": admin.pk, "username": admin.username, "revoked_tokens": revoked},
            message="密码已修改，其它设备的登录已失效",
        )
