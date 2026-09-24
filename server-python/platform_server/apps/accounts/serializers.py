"""登录相关的序列化器。

三件事：**校验入参**、**输出管理员信息**、**签发/吊销令牌**。

口径统一：

* 口令错误与账号不存在返回同一个错误码（`ERR_LOGIN_FAILED`），不泄露账号是否存在；
* 被禁用的账号返回 `ERR_ACCOUNT_DISABLED`（这个必须明确，否则运营会以为是密码错）；
* 输出里**永远不含** `password` 字段。

认证失败时抛的是 `apps.common.exceptions` 里的 `LoginFailed` / `AccountDisabled`，
而不是 DRF 的 `ValidationError`——原因见那两个类的注释：只有异常类型本身
能携带业务码，统一异常处理器才不会把它压成通用的 `ERR_BAD_REQUEST`。
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.hashers import make_password
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common import ip
from apps.common.exceptions import AccountDisabled, LoginFailed

from .models import AdminUser


class AdminUserSerializer(serializers.ModelSerializer[AdminUser]):
    """管理员信息输出。

    只暴露前端需要的字段，`password`、`is_staff` 之类的内部字段一律不出网。
    """

    role_display = serializers.CharField(source="get_role_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = AdminUser
        fields = (
            "id",
            "username",
            "nickname",
            "display_name",
            "email",
            "role",
            "role_display",
            "status",
            "status_display",
            "is_superuser",
            "last_login",
            "last_login_ip",
            "created_at",
        )
        read_only_fields = fields


class LoginSerializer(serializers.Serializer[Any]):
    """登录入参。

    认证在**序列化器**里完成（而不是视图里），入参校验与身份校验放在一起，
    `validate` 抛出的 `LoginFailed` / `AccountDisabled` 由统一异常处理器
    翻译成对应的业务码。
    """

    username = serializers.CharField(
        max_length=150,
        trim_whitespace=True,
        error_messages={"blank": "请输入账号", "required": "请输入账号"},
    )
    password = serializers.CharField(
        max_length=128,
        trim_whitespace=False,
        write_only=True,
        style={"input_type": "password"},
        error_messages={"blank": "请输入密码", "required": "请输入密码"},
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """认证账号口令，并把管理员对象挂到 `validated_data["admin"]`。

        认证刻意不用 `django.contrib.auth.authenticate()`，而是自己走
        "按账号名取候选 → 查状态 → 验口令"三步，原因有三：

        1. **账号名要大小写不敏感**。运营在登录框里敲 `Admin` 也应该进得去，
           而 `ModelBackend` 的 `get_by_natural_key` 对 `username` 是精确匹配
           （`USERNAME_FIELD` 不是 `email`，所以不走 `iexact` 那条分支）。
        2. **要能区分"被禁用"和"口令错误"**。`authenticate()` 对
           `is_active=False` 的用户直接返回 `None`，两种原因就混在一起了。
        3. 口令哈希校验用 `check_password()`，它会在需要时**就地升级哈希算法**
           （`set_password` 写回），这是 Django 的既有能力，不丢。
        """
        username: str = attrs["username"]
        password: str = attrs["password"]

        # 只查 AdminUser 表。玩家的 `t_accounts` / `t_users` 不在 Django 的
        # ORM 里，物理上不可能被这个查询命中——这是"账号体系隔离"的第一道闸。
        candidate = AdminUser.objects.filter(username__iexact=username).first()

        if candidate is None:
            # 账号不存在也走一次等价耗时的哈希运算，让响应时间与"账号存在"
            # 接近，不给出可计时的账号枚举信号。
            make_password(password)
            raise LoginFailed()

        if not candidate.is_enabled:
            # 账号已停用：明确说明原因。这确实暴露了"该账号存在"，
            # 但只对已被停用的账号成立，且运营需要看到这条信息，风险可接受。
            raise AccountDisabled()

        if not candidate.check_password(password):
            raise LoginFailed()

        # 口令正确且账号启用。`check_password` 可能在内存里升级了哈希，
        # 这里同步落库（只有真的变了才会产生写操作）。
        candidate.save(update_fields=["password", "updated_at"])

        attrs["admin"] = candidate
        return attrs


class RefreshSerializer(serializers.Serializer[Any]):
    """刷新入参，并在这里完成令牌轮换。

    轮换逻辑照搬 SimpleJWT `TokenRefreshSerializer` 的既有行为（读
    `ROTATE_REFRESH_TOKENS` / `BLACKLIST_AFTER_ROTATION`），只是额外把
    `admin_id` 记下来，供视图核对账号是否仍然启用。

    放在序列化器里的原因：`validate()` 抛错时**不会**执行轮换，
    而如果先自己轮换再校验，一次失败的刷新就会白白作废旧令牌。
    """

    refresh = serializers.CharField(
        error_messages={"blank": "缺少 refresh 令牌", "required": "缺少 refresh 令牌"},
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        #: 刷新成功后解析出的管理员主键；失败时为 `None`。
        self.admin_id: int | None = None

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """校验 refresh 并按配置轮换。"""
        from rest_framework_simplejwt.exceptions import TokenError
        from rest_framework_simplejwt.settings import api_settings
        from rest_framework_simplejwt.tokens import RefreshToken as RefreshTokenClass

        raw: str = attrs["refresh"]
        try:
            token = RefreshTokenClass(raw)
        except TokenError:
            # 交给视图翻译成 ERR_TOKEN_INVALID（统一外壳）。
            raise

        self.admin_id = token.get(api_settings.USER_ID_CLAIM)

        data: dict[str, Any] = {"access": str(token.access_token)}

        if api_settings.ROTATE_REFRESH_TOKENS:
            if api_settings.BLACKLIST_AFTER_ROTATION:
                try:
                    token.blacklist()
                except AttributeError:
                    # `token_blacklist` 应用没装时才可能走到这里（本项目装了）。
                    pass
            token.set_jti()
            token.set_exp()
            token.set_iat()
            data["refresh"] = str(token)
            # 前端用它做过期提醒，不必自己解析 JWT。
            data["refresh_expires_at"] = int(token["exp"])

        return data


class LogoutSerializer(serializers.Serializer[Any]):
    """退出入参。

    `refresh` 可选：拿不到 refresh（例如前端只有 access）时也要允许退出，
    服务端至少能清掉自己的记录，客户端清本地状态即可。
    """

    refresh = serializers.CharField(required=False, allow_blank=True, default="")


def issue_tokens(admin: AdminUser, request: object | None = None) -> dict[str, Any]:
    """为管理员签发一对令牌，并刷新其最后登录信息。

    :param admin: 已通过口令校验的管理员。
    :param request: 当前请求，用于取来源 IP。
    :return: `{"access": ..., "refresh": ..., "access_expires_at": ..., "user": {...}}`
    """
    refresh = RefreshToken.for_user(admin)
    # 令牌里带一份角色快照，方便排查"这个 token 当时是什么权限"。
    refresh["role"] = admin.effective_role
    refresh["username"] = admin.username

    admin.last_login = timezone.now()
    admin.last_login_ip = ip.get_client_ip(request) if request is not None else None
    admin.save(update_fields=["last_login", "last_login_ip", "updated_at"])

    access = refresh.access_token
    return {
        "access": str(access),
        "refresh": str(refresh),
        # 前端用它做过期提醒，避免只靠解析 JWT。
        "access_expires_at": int(access["exp"]),
        "user": AdminUserSerializer(admin).data,
    }


def blacklist_refresh_token(raw_token: str) -> bool:
    """把 refresh 令牌加入黑名单（退出登录）。

    :param raw_token: 前端传来的 refresh 字符串。
    :return: 成功吊销返回 `True`；令牌无效/已吊销/缺失返回 `False`
        （对调用方来说"已经无效"和"刚被吊销"是同一个结果，不算错误）。
    """
    if not raw_token:
        return False

    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.tokens import RefreshToken as RefreshTokenClass

    try:
        token = RefreshTokenClass(raw_token)
        token.blacklist()
    except TokenError:
        return False
    return True
